// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![cfg_attr(
  feature = "cargo-clippy",
  deny(
    clippy, default_trait_access, expl_impl_clone_on_copy, if_not_else, needless_continue,
    single_match_else, unseparated_literal_suffix, used_underscore_binding
  )
)]
// It is often more clear to show that nothing is being moved.
#![cfg_attr(feature = "cargo-clippy", allow(match_ref_pats))]
// Subjective style.
#![cfg_attr(feature = "cargo-clippy", allow(len_without_is_empty, redundant_field_names))]
// Default isn't as big a deal as people seem to think it is.
#![cfg_attr(feature = "cargo-clippy", allow(new_without_default, new_without_default_derive))]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![cfg_attr(feature = "cargo-clippy", allow(mutex_atomic))]

mod glob_matching;
pub use glob_matching::GlobMatching;
mod snapshot;
pub use snapshot::{
  OneOffStoreFileByDigest, Snapshot, StoreFileByDigest, EMPTY_DIGEST, EMPTY_FINGERPRINT,
};
mod store;
pub use store::Store;
mod pool;
pub use pool::ResettablePool;

extern crate bazel_protos;
#[macro_use]
extern crate boxfuture;
extern crate byteorder;
extern crate bytes;
extern crate digest;
extern crate futures;
extern crate futures_cpupool;
extern crate glob;
extern crate grpcio;
extern crate hashing;
extern crate ignore;
extern crate indexmap;
extern crate itertools;
#[macro_use]
extern crate lazy_static;
extern crate lmdb;
#[macro_use]
extern crate log;
#[cfg(test)]
extern crate mock;
extern crate protobuf;
extern crate resettable;
extern crate sha2;
#[cfg(test)]
extern crate tempfile;
#[cfg(test)]
extern crate testutil;

use std::cmp::min;
use std::io::{self, Read};
use std::os::unix::fs::PermissionsExt;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use std::{fmt, fs};

use bytes::Bytes;
use futures::future::{self, Future};
use glob::Pattern;
use ignore::gitignore::{Gitignore, GitignoreBuilder};

use boxfuture::{BoxFuture, Boxable};

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Stat {
  Link(Link),
  Dir(Dir),
  File(File),
}

impl Stat {
  pub fn path(&self) -> &Path {
    match self {
      &Stat::Dir(Dir(ref p)) => p.as_path(),
      &Stat::File(File { path: ref p, .. }) => p.as_path(),
      &Stat::Link(Link(ref p)) => p.as_path(),
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Link(pub PathBuf);

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Dir(pub PathBuf);

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct File {
  pub path: PathBuf,
  pub is_executable: bool,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum PathStat {
  Dir {
    // The symbolic name of some filesystem Path, which is context specific.
    path: PathBuf,
    // The canonical Stat that underlies the Path.
    stat: Dir,
  },
  File {
    // The symbolic name of some filesystem Path, which is context specific.
    path: PathBuf,
    // The canonical Stat that underlies the Path.
    stat: File,
  },
}

impl PathStat {
  pub fn dir(path: PathBuf, stat: Dir) -> PathStat {
    PathStat::Dir {
      path: path,
      stat: stat,
    }
  }

  pub fn file(path: PathBuf, stat: File) -> PathStat {
    PathStat::File {
      path: path,
      stat: stat,
    }
  }

  pub fn path(&self) -> &Path {
    match self {
      &PathStat::Dir { ref path, .. } => path.as_path(),
      &PathStat::File { ref path, .. } => path.as_path(),
    }
  }
}

#[derive(Debug, Eq, PartialEq)]
pub struct DirectoryListing(pub Vec<Stat>);

#[derive(Debug)]
pub struct GitignoreStyleExcludes {
  patterns: Vec<String>,
  gitignore: Gitignore,
}

impl GitignoreStyleExcludes {
  fn create(patterns: &[String]) -> Result<Arc<Self>, String> {
    if patterns.is_empty() {
      return Ok(EMPTY_IGNORE.clone());
    }

    let gitignore = Self::create_gitignore(patterns)
      .map_err(|e| format!("Could not parse glob excludes {:?}: {:?}", patterns, e))?;

    Ok(Arc::new(Self {
      patterns: patterns.to_vec(),
      gitignore,
    }))
  }

  fn create_gitignore(patterns: &[String]) -> Result<Gitignore, ignore::Error> {
    let mut ignore_builder = GitignoreBuilder::new("");
    for pattern in patterns {
      ignore_builder.add_line(None, pattern.as_str())?;
    }
    ignore_builder.build()
  }

  fn exclude_patterns(&self) -> &[String] {
    self.patterns.as_slice()
  }

  fn is_ignored(&self, stat: &Stat) -> bool {
    let is_dir = match stat {
      &Stat::Dir(_) => true,
      _ => false,
    };
    match self.gitignore.matched(stat.path(), is_dir) {
      ignore::Match::None | ignore::Match::Whitelist(_) => false,
      ignore::Match::Ignore(_) => true,
    }
  }
}

lazy_static! {
  static ref PARENT_DIR: &'static str = "..";
  static ref SINGLE_STAR_GLOB: Pattern = Pattern::new("*").unwrap();
  static ref DOUBLE_STAR: &'static str = "**";
  static ref DOUBLE_STAR_GLOB: Pattern = Pattern::new(*DOUBLE_STAR).unwrap();
  static ref EMPTY_IGNORE: Arc<GitignoreStyleExcludes> = Arc::new(GitignoreStyleExcludes {
    patterns: vec![],
    gitignore: Gitignore::empty(),
  });
  static ref MISSING_GLOB_SOURCE: GlobParsedSource = GlobParsedSource(String::from(""));
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum PathGlob {
  Wildcard {
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Pattern,
  },
  DirWildcard {
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Pattern,
    remainder: Vec<Pattern>,
  },
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct GlobParsedSource(String);

#[derive(Clone, Debug)]
pub struct PathGlobIncludeEntry {
  pub input: GlobParsedSource,
  pub globs: Vec<PathGlob>,
}

impl PathGlobIncludeEntry {
  fn to_sourced_globs(&self) -> Vec<GlobWithSource> {
    self
      .globs
      .clone()
      .into_iter()
      .map(|path_glob| GlobWithSource {
        path_glob,
        source: GlobSource::ParsedInput(self.input.clone()),
      })
      .collect()
  }
}

impl PathGlob {
  fn wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: Pattern) -> PathGlob {
    PathGlob::Wildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
    }
  }

  fn dir_wildcard(
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Pattern,
    remainder: Vec<Pattern>,
  ) -> PathGlob {
    PathGlob::DirWildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
      remainder: remainder,
    }
  }

  pub fn create(filespecs: &[String]) -> Result<Vec<PathGlob>, String> {
    // Getting a Vec<PathGlob> per filespec is needed to create a `PathGlobs`, but we don't need
    // that here.
    let filespecs_globs = Self::spread_filespecs(filespecs)?;
    let all_globs = Self::flatten_entries(filespecs_globs);
    Ok(all_globs)
  }

  fn flatten_entries(entries: Vec<PathGlobIncludeEntry>) -> Vec<PathGlob> {
    entries.into_iter().flat_map(|entry| entry.globs).collect()
  }

  fn spread_filespecs(filespecs: &[String]) -> Result<Vec<PathGlobIncludeEntry>, String> {
    let mut spec_globs_map = Vec::new();
    for filespec in filespecs {
      let canonical_dir = Dir(PathBuf::new());
      let symbolic_path = PathBuf::new();
      spec_globs_map.push(PathGlobIncludeEntry {
        input: GlobParsedSource(filespec.clone()),
        globs: PathGlob::parse(canonical_dir, symbolic_path, filespec)?,
      });
    }
    Ok(spec_globs_map)
  }

  ///
  /// Given a filespec String relative to a canonical Dir and path, split it into path components
  /// while eliminating consecutive '**'s (to avoid repetitive traversing), and parse it to a
  /// series of PathGlob objects.
  ///
  fn parse(
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    filespec: &str,
  ) -> Result<Vec<PathGlob>, String> {
    let mut parts = Vec::new();
    let mut prev_was_doublestar = false;
    for component in Path::new(filespec).components() {
      let part = match component {
        Component::Prefix(..) | Component::RootDir => {
          return Err(format!("Absolute paths not supported: {:?}", filespec))
        }
        Component::CurDir => continue,
        c => c.as_os_str(),
      };

      // Ignore repeated doublestar instances.
      let cur_is_doublestar = *DOUBLE_STAR == part;
      if prev_was_doublestar && cur_is_doublestar {
        continue;
      }
      prev_was_doublestar = cur_is_doublestar;

      // NB: Because the filespec is a String input, calls to `to_str_lossy` are not lossy; the
      // use of `Path` is strictly for os-independent Path parsing.
      parts.push(
        Pattern::new(&part.to_string_lossy())
          .map_err(|e| format!("Could not parse {:?} as a glob: {:?}", filespec, e))?,
      );
    }

    PathGlob::parse_globs(canonical_dir, symbolic_path, &parts)
  }

  ///
  /// Given a filespec as Patterns, create a series of PathGlob objects.
  ///
  fn parse_globs(
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    parts: &[Pattern],
  ) -> Result<Vec<PathGlob>, String> {
    if parts.is_empty() {
      Ok(vec![])
    } else if *DOUBLE_STAR == parts[0].as_str() {
      if parts.len() == 1 {
        // Per https://git-scm.com/docs/gitignore:
        //  "A trailing '/**' matches everything inside. For example, 'abc/**' matches all files
        //  inside directory "abc", relative to the location of the .gitignore file, with infinite
        //  depth."
        return Ok(vec![
          PathGlob::dir_wildcard(
            canonical_dir.clone(),
            symbolic_path.clone(),
            SINGLE_STAR_GLOB.clone(),
            vec![DOUBLE_STAR_GLOB.clone()],
          ),
          PathGlob::wildcard(canonical_dir, symbolic_path, SINGLE_STAR_GLOB.clone()),
        ]);
      }

      // There is a double-wildcard in a dirname of the path: double wildcards are recursive,
      // so there are two remainder possibilities: one with the double wildcard included, and the
      // other without.
      let pathglob_with_doublestar = PathGlob::dir_wildcard(
        canonical_dir.clone(),
        symbolic_path.clone(),
        SINGLE_STAR_GLOB.clone(),
        parts[0..].to_vec(),
      );
      let pathglob_no_doublestar = if parts.len() == 2 {
        PathGlob::wildcard(canonical_dir, symbolic_path, parts[1].clone())
      } else {
        PathGlob::dir_wildcard(
          canonical_dir,
          symbolic_path,
          parts[1].clone(),
          parts[2..].to_vec(),
        )
      };
      Ok(vec![pathglob_with_doublestar, pathglob_no_doublestar])
    } else if *PARENT_DIR == parts[0].as_str() {
      // A request for the parent of `canonical_dir`: since we've already expanded the directory
      // to make it canonical, we can safely drop it directly and recurse without this component.
      // The resulting symbolic path will continue to contain a literal `..`.
      let mut canonical_dir_parent = canonical_dir;
      let mut symbolic_path_parent = symbolic_path;
      if !canonical_dir_parent.0.pop() {
        return Err(format!(
          "Globs may not traverse outside the root: {:?}",
          parts
        ));
      }
      symbolic_path_parent.push(Path::new(*PARENT_DIR));
      PathGlob::parse_globs(canonical_dir_parent, symbolic_path_parent, &parts[1..])
    } else if parts.len() == 1 {
      // This is the path basename.
      Ok(vec![PathGlob::wildcard(
        canonical_dir,
        symbolic_path,
        parts[0].clone(),
      )])
    } else {
      // This is a path dirname.
      Ok(vec![PathGlob::dir_wildcard(
        canonical_dir,
        symbolic_path,
        parts[0].clone(),
        parts[1..].to_vec(),
      )])
    }
  }
}

#[derive(Debug)]
pub enum StrictGlobMatching {
  Error,
  Warn,
  Ignore,
}

impl StrictGlobMatching {
  // TODO(cosmicexplorer): match this up with the allowed values for the GlobMatchErrorBehavior type
  // in python somehow?
  pub fn create(behavior: &str) -> Result<Self, String> {
    match behavior {
      "ignore" => Ok(StrictGlobMatching::Ignore),
      "warn" => Ok(StrictGlobMatching::Warn),
      "error" => Ok(StrictGlobMatching::Error),
      _ => Err(format!(
        "Unrecognized strict glob matching behavior: {}.",
        behavior,
      )),
    }
  }

  pub fn should_check_glob_matches(&self) -> bool {
    match self {
      &StrictGlobMatching::Ignore => false,
      _ => true,
    }
  }

  pub fn should_throw_on_error(&self) -> bool {
    match self {
      &StrictGlobMatching::Error => true,
      _ => false,
    }
  }
}

#[derive(Debug)]
pub enum Conjunction {
  And,
  Or,
}

impl Conjunction {
  pub fn create(spec: &str) -> Result<Self, String> {
    match spec {
      "and" => Ok(Conjunction::And),
      "or" => Ok(Conjunction::Or),
      _ => Err(format!("Unrecognized conjunction: {}.", spec)),
    }
  }
}

#[derive(Debug)]
pub struct PathGlobs {
  include: Vec<PathGlobIncludeEntry>,
  exclude: Arc<GitignoreStyleExcludes>,
  strict_match_behavior: StrictGlobMatching,
  conjunction: Conjunction,
}

impl PathGlobs {
  pub fn create(
    include: &[String],
    exclude: &[String],
    strict_match_behavior: StrictGlobMatching,
    conjunction: Conjunction,
  ) -> Result<PathGlobs, String> {
    let include = PathGlob::spread_filespecs(include)?;
    Self::create_with_globs_and_match_behavior(include, exclude, strict_match_behavior, conjunction)
  }

  fn create_with_globs_and_match_behavior(
    include: Vec<PathGlobIncludeEntry>,
    exclude: &[String],
    strict_match_behavior: StrictGlobMatching,
    conjunction: Conjunction,
  ) -> Result<PathGlobs, String> {
    let gitignore_excludes = GitignoreStyleExcludes::create(exclude)?;
    Ok(PathGlobs {
      include,
      exclude: gitignore_excludes,
      strict_match_behavior,
      conjunction,
    })
  }

  pub fn from_globs(include: Vec<PathGlob>) -> Result<PathGlobs, String> {
    let include = include
      .into_iter()
      .map(|glob| PathGlobIncludeEntry {
        input: MISSING_GLOB_SOURCE.clone(),
        globs: vec![glob],
      })
      .collect();
    // An empty exclude becomes EMPTY_IGNORE.
    PathGlobs::create_with_globs_and_match_behavior(
      include,
      &[],
      StrictGlobMatching::Ignore,
      Conjunction::And,
    )
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum GlobSource {
  ParsedInput(GlobParsedSource),
  ParentGlob(PathGlob),
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct GlobWithSource {
  path_glob: PathGlob,
  source: GlobSource,
}

///
/// All Stats consumed or return by this type are relative to the root.
///
pub struct PosixFS {
  root: Dir,
  pool: Arc<ResettablePool>,
  ignore: Arc<GitignoreStyleExcludes>,
}

impl PosixFS {
  pub fn new<P: AsRef<Path>>(
    root: P,
    pool: Arc<ResettablePool>,
    ignore_patterns: &[String],
  ) -> Result<PosixFS, String> {
    let root: &Path = root.as_ref();
    let canonical_root = root
      .canonicalize()
      .and_then(|canonical| {
        canonical.metadata().and_then(|metadata| {
          if metadata.is_dir() {
            Ok(Dir(canonical))
          } else {
            Err(io::Error::new(
              io::ErrorKind::InvalidInput,
              "Not a directory.",
            ))
          }
        })
      })
      .map_err(|e| format!("Could not canonicalize root {:?}: {:?}", root, e))?;

    let ignore = GitignoreStyleExcludes::create(&ignore_patterns).map_err(|e| {
      format!(
        "Could not parse build ignore inputs {:?}: {:?}",
        ignore_patterns, e
      )
    })?;
    Ok(PosixFS {
      root: canonical_root,
      pool: pool,
      ignore: ignore,
    })
  }

  fn scandir_sync(root: &Path, dir_relative_to_root: &Dir) -> Result<Vec<Stat>, io::Error> {
    let dir_abs = root.join(&dir_relative_to_root.0);
    let mut stats: Vec<Stat> = dir_abs
      .read_dir()?
      .map(|readdir| {
        let dir_entry = readdir?;
        let get_metadata = || std::fs::metadata(dir_abs.join(dir_entry.file_name()));
        PosixFS::stat_internal(
          dir_relative_to_root.0.join(dir_entry.file_name()),
          dir_entry.file_type()?,
          &dir_abs,
          get_metadata,
        )
      })
      .collect::<Result<Vec<_>, io::Error>>()?;
    stats.sort_by(|s1, s2| s1.path().cmp(s2.path()));
    Ok(stats)
  }

  pub fn is_ignored(&self, stat: &Stat) -> bool {
    self.ignore.is_ignored(stat)
  }

  pub fn read_file(&self, file: &File) -> BoxFuture<FileContent, io::Error> {
    let path = file.path.clone();
    let path_abs = self.root.0.join(&file.path);
    self
      .pool
      .spawn_fn(move || {
        std::fs::File::open(&path_abs).and_then(|mut f| {
          let mut content = Vec::new();
          f.read_to_end(&mut content)?;
          Ok(FileContent {
            path: path,
            content: Bytes::from(content),
          })
        })
      })
      .to_boxed()
  }

  pub fn read_link(&self, link: &Link) -> BoxFuture<PathBuf, io::Error> {
    let link_parent = link.0.parent().map(|p| p.to_owned());
    let link_abs = self.root.0.join(link.0.as_path()).to_owned();
    self
      .pool
      .spawn_fn(move || {
        link_abs.read_link().and_then(|path_buf| {
          if path_buf.is_absolute() {
            Err(io::Error::new(
              io::ErrorKind::InvalidData,
              format!("Absolute symlink: {:?}", link_abs),
            ))
          } else {
            link_parent
              .map(|parent| parent.join(path_buf))
              .ok_or_else(|| {
                io::Error::new(
                  io::ErrorKind::InvalidData,
                  format!("Symlink without a parent?: {:?}", link_abs),
                )
              })
          }
        })
      })
      .to_boxed()
  }

  ///
  /// Makes a Stat for path_for_stat relative to absolute_path_to_root.
  ///
  fn stat_internal<F>(
    path_for_stat: PathBuf,
    file_type: std::fs::FileType,
    absolute_path_to_root: &Path,
    get_metadata: F,
  ) -> Result<Stat, io::Error>
  where
    F: FnOnce() -> Result<fs::Metadata, io::Error>,
  {
    if !path_for_stat.is_relative() {
      return Err(io::Error::new(
        io::ErrorKind::InvalidInput,
        format!(
          "Argument path_for_stat to PosixFS::stat must be relative path, got {:?}",
          path_for_stat
        ),
      ));
    }
    // TODO: Make this an instance method, and stop having to check this every call.
    if !absolute_path_to_root.is_absolute() {
      return Err(io::Error::new(
        io::ErrorKind::InvalidInput,
        format!(
          "Argument absolute_path_to_root to PosixFS::stat must be absolute path, got {:?}",
          absolute_path_to_root
        ),
      ));
    }
    if file_type.is_dir() {
      Ok(Stat::Dir(Dir(path_for_stat)))
    } else if file_type.is_file() {
      let is_executable = get_metadata()?.permissions().mode() & 0o100 == 0o100;
      Ok(Stat::File(File {
        path: path_for_stat,
        is_executable: is_executable,
      }))
    } else if file_type.is_symlink() {
      Ok(Stat::Link(Link(path_for_stat)))
    } else {
      Err(io::Error::new(
        io::ErrorKind::InvalidData,
        format!(
          "Expected File, Dir or Link, but {:?} (relative to {:?}) was a {:?}",
          path_for_stat, absolute_path_to_root, file_type
        ),
      ))
    }
  }

  pub fn stat(&self, relative_path: PathBuf) -> Result<Stat, io::Error> {
    PosixFS::stat_path(relative_path, &self.root.0)
  }

  fn stat_path(relative_path: PathBuf, root: &Path) -> Result<Stat, io::Error> {
    let metadata = fs::symlink_metadata(root.join(&relative_path))?;
    PosixFS::stat_internal(relative_path, metadata.file_type(), &root, || Ok(metadata))
  }

  pub fn scandir(&self, dir: &Dir) -> BoxFuture<DirectoryListing, io::Error> {
    let dir = dir.to_owned();
    let root = self.root.0.clone();
    self
      .pool
      .spawn_fn(move || PosixFS::scandir_sync(&root, &dir))
      .map(DirectoryListing)
      .to_boxed()
  }
}

impl VFS<io::Error> for Arc<PosixFS> {
  fn read_link(&self, link: &Link) -> BoxFuture<PathBuf, io::Error> {
    PosixFS::read_link(self, link)
  }

  fn scandir(&self, dir: Dir) -> BoxFuture<Arc<DirectoryListing>, io::Error> {
    PosixFS::scandir(self, &dir).map(Arc::new).to_boxed()
  }

  fn is_ignored(&self, stat: &Stat) -> bool {
    PosixFS::is_ignored(self, stat)
  }

  fn mk_error(msg: &str) -> io::Error {
    io::Error::new(io::ErrorKind::Other, msg)
  }
}

pub trait PathStatGetter<E> {
  fn path_stats(&self, paths: Vec<PathBuf>) -> BoxFuture<Vec<Option<PathStat>>, E>;
}

impl PathStatGetter<io::Error> for Arc<PosixFS> {
  fn path_stats(&self, paths: Vec<PathBuf>) -> BoxFuture<Vec<Option<PathStat>>, io::Error> {
    future::join_all(
      paths
        .into_iter()
        .map(|path| {
          let root = self.root.0.clone();
          let fs = self.clone();
          self
            .pool
            .spawn_fn(move || PosixFS::stat_path(path, &root))
            .then(|stat_result| match stat_result {
              Ok(v) => Ok(Some(v)),
              Err(err) => match err.kind() {
                io::ErrorKind::NotFound => Ok(None),
                _ => Err(err),
              },
            })
            .and_then(move |maybe_stat| {
              match maybe_stat {
                // Note: This will drop PathStats for symlinks which don't point anywhere.
                Some(Stat::Link(link)) => fs.canonicalize(link.0.clone(), &link),
                Some(Stat::Dir(dir)) => {
                  future::ok(Some(PathStat::dir(dir.0.clone(), dir))).to_boxed()
                }
                Some(Stat::File(file)) => {
                  future::ok(Some(PathStat::file(file.path.clone(), file))).to_boxed()
                }
                None => future::ok(None).to_boxed(),
              }
            })
        })
        .collect::<Vec<_>>(),
    ).to_boxed()
  }
}

///
/// A context for filesystem operations parameterized on an error type 'E'.
///
pub trait VFS<E: Send + Sync + 'static>: Clone + Send + Sync + 'static {
  fn read_link(&self, link: &Link) -> BoxFuture<PathBuf, E>;
  fn scandir(&self, dir: Dir) -> BoxFuture<Arc<DirectoryListing>, E>;
  fn is_ignored(&self, stat: &Stat) -> bool;
  fn mk_error(msg: &str) -> E;
}

pub struct FileContent {
  pub path: PathBuf,
  pub content: Bytes,
}

impl fmt::Debug for FileContent {
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
    let len = min(self.content.len(), 5);
    let describer = if len < self.content.len() {
      "starting "
    } else {
      ""
    };
    write!(
      f,
      "FileContent(path={:?}, content={} bytes {}{:?})",
      self.path,
      self.content.len(),
      describer,
      &self.content[..len]
    )
  }
}

// Like std::fs::create_dir_all, except handles concurrent calls among multiple
// threads or processes. Originally lifted from rustc.
pub fn safe_create_dir_all_ioerror(path: &Path) -> Result<(), io::Error> {
  match fs::create_dir(path) {
    Ok(()) => return Ok(()),
    Err(ref e) if e.kind() == io::ErrorKind::AlreadyExists => return Ok(()),
    Err(ref e) if e.kind() == io::ErrorKind::NotFound => {}
    Err(e) => return Err(e),
  }
  match path.parent() {
    Some(p) => try!(safe_create_dir_all_ioerror(p)),
    None => return Ok(()),
  }
  match fs::create_dir(path) {
    Ok(()) => Ok(()),
    Err(ref e) if e.kind() == io::ErrorKind::AlreadyExists => Ok(()),
    Err(e) => Err(e),
  }
}

fn safe_create_dir_all(path: &Path) -> Result<(), String> {
  safe_create_dir_all_ioerror(path)
    .map_err(|e| format!("Failed to create dir {:?} due to {:?}", path, e))
}

#[cfg(test)]
mod posixfs_test {
  extern crate tempfile;
  extern crate testutil;

  use super::{
    Dir, DirectoryListing, File, Link, PathStat, PathStatGetter, PosixFS, ResettablePool, Stat,
  };
  use futures::Future;
  use std;
  use std::path::{Path, PathBuf};
  use std::sync::Arc;
  use testutil::make_file;

  #[test]
  fn is_executable_false() {
    let dir = tempfile::TempDir::new().unwrap();
    make_file(&dir.path().join("marmosets"), &[], 0o611);
    assert_only_file_is_executable(dir.path(), false);
  }

  #[test]
  fn is_executable_true() {
    let dir = tempfile::TempDir::new().unwrap();
    make_file(&dir.path().join("photograph_marmosets"), &[], 0o700);
    assert_only_file_is_executable(dir.path(), true);
  }

  #[test]
  fn read_file() {
    let dir = tempfile::TempDir::new().unwrap();
    let path = PathBuf::from("marmosets");
    let content = "cute".as_bytes().to_vec();
    make_file(
      &std::fs::canonicalize(dir.path()).unwrap().join(&path),
      &content,
      0o600,
    );
    let fs = new_posixfs(&dir.path());
    let file_content =
      fs.read_file(&File {
        path: path.clone(),
        is_executable: false,
      }).wait()
        .unwrap();
    assert_eq!(file_content.path, path);
    assert_eq!(file_content.content, content);
  }

  #[test]
  fn read_file_missing() {
    let dir = tempfile::TempDir::new().unwrap();
    new_posixfs(&dir.path())
      .read_file(&File {
        path: PathBuf::from("marmosets"),
        is_executable: false,
      })
      .wait()
      .expect_err("Expected error");
  }

  #[test]
  fn stat_executable_file() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("photograph_marmosets");
    make_file(&dir.path().join(&path), &[], 0o700);
    assert_eq!(
      posix_fs.stat(path.clone()).unwrap(),
      super::Stat::File(File {
        path: path,
        is_executable: true,
      })
    )
  }

  #[test]
  fn stat_nonexecutable_file() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("marmosets");
    make_file(&dir.path().join(&path), &[], 0o600);
    assert_eq!(
      posix_fs.stat(path.clone()).unwrap(),
      super::Stat::File(File {
        path: path,
        is_executable: false,
      })
    )
  }

  #[test]
  fn stat_dir() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();
    assert_eq!(
      posix_fs.stat(path.clone()).unwrap(),
      super::Stat::Dir(Dir(path))
    )
  }

  #[test]
  fn stat_symlink() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("marmosets");
    make_file(&dir.path().join(&path), &[], 0o600);

    let link_path = PathBuf::from("remarkably_similar_marmoset");
    std::os::unix::fs::symlink(&dir.path().join(path), dir.path().join(&link_path)).unwrap();
    assert_eq!(
      posix_fs.stat(link_path.clone()).unwrap(),
      super::Stat::Link(Link(link_path))
    )
  }

  #[test]
  fn stat_other() {
    new_posixfs("/dev")
      .stat(PathBuf::from("null"))
      .expect_err("Want error");
  }

  #[test]
  fn stat_missing() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(&dir.path());
    posix_fs
      .stat(PathBuf::from("no_marmosets"))
      .expect_err("Want error");
  }

  #[test]
  fn scandir_empty() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("empty_enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();
    assert_eq!(
      posix_fs.scandir(&Dir(path)).wait().unwrap(),
      DirectoryListing(vec![])
    );
  }

  #[test]
  fn scandir() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();

    let a_marmoset = path.join("a_marmoset");
    let feed = path.join("feed");
    let hammock = path.join("hammock");
    let remarkably_similar_marmoset = path.join("remarkably_similar_marmoset");
    let sneaky_marmoset = path.join("sneaky_marmoset");

    make_file(&dir.path().join(&feed), &[], 0o700);
    make_file(&dir.path().join(&a_marmoset), &[], 0o600);
    make_file(&dir.path().join(&sneaky_marmoset), &[], 0o600);
    std::os::unix::fs::symlink(
      &dir.path().join(&a_marmoset),
      dir
        .path()
        .join(&dir.path().join(&remarkably_similar_marmoset)),
    ).unwrap();
    std::fs::create_dir(dir.path().join(&hammock)).unwrap();
    make_file(
      &dir.path().join(&hammock).join("napping_marmoset"),
      &[],
      0o600,
    );

    assert_eq!(
      posix_fs.scandir(&Dir(path)).wait().unwrap(),
      DirectoryListing(vec![
        Stat::File(File {
          path: a_marmoset,
          is_executable: false,
        }),
        Stat::File(File {
          path: feed,
          is_executable: true,
        }),
        Stat::Dir(Dir(hammock)),
        Stat::Link(Link(remarkably_similar_marmoset)),
        Stat::File(File {
          path: sneaky_marmoset,
          is_executable: false,
        }),
      ])
    );
  }

  #[test]
  fn scandir_missing() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(&dir.path());
    posix_fs
      .scandir(&Dir(PathBuf::from("no_marmosets_here")))
      .wait()
      .expect_err("Want error");
  }

  #[test]
  fn path_stats_for_paths() {
    let dir = tempfile::TempDir::new().unwrap();
    let root_path = dir.path();

    // File tree:
    // dir
    // dir/recursive_symlink -> ../symlink -> executable_file
    // dir_symlink -> dir
    // executable_file
    // regular_file
    // symlink -> executable_file
    // symlink_to_nothing -> doesnotexist

    make_file(&root_path.join("executable_file"), &[], 0o700);
    make_file(&root_path.join("regular_file"), &[], 0o600);
    std::fs::create_dir(&root_path.join("dir")).unwrap();
    std::os::unix::fs::symlink("executable_file", &root_path.join("symlink")).unwrap();
    std::os::unix::fs::symlink(
      "../symlink",
      &root_path.join("dir").join("recursive_symlink"),
    ).unwrap();
    std::os::unix::fs::symlink("dir", &root_path.join("dir_symlink")).unwrap();
    std::os::unix::fs::symlink("doesnotexist", &root_path.join("symlink_to_nothing")).unwrap();

    let posix_fs = Arc::new(new_posixfs(&root_path));
    let path_stats = posix_fs
      .path_stats(vec![
        PathBuf::from("executable_file"),
        PathBuf::from("regular_file"),
        PathBuf::from("dir"),
        PathBuf::from("symlink"),
        PathBuf::from("dir").join("recursive_symlink"),
        PathBuf::from("dir_symlink"),
        PathBuf::from("symlink_to_nothing"),
        PathBuf::from("doesnotexist"),
      ])
      .wait()
      .unwrap();
    let v: Vec<Option<PathStat>> = vec![
      Some(PathStat::file(
        PathBuf::from("executable_file"),
        File {
          path: PathBuf::from("executable_file"),
          is_executable: true,
        },
      )),
      Some(PathStat::file(
        PathBuf::from("regular_file"),
        File {
          path: PathBuf::from("regular_file"),
          is_executable: false,
        },
      )),
      Some(PathStat::dir(
        PathBuf::from("dir"),
        Dir(PathBuf::from("dir")),
      )),
      Some(PathStat::file(
        PathBuf::from("symlink"),
        File {
          path: PathBuf::from("executable_file"),
          is_executable: true,
        },
      )),
      Some(PathStat::file(
        PathBuf::from("dir").join("recursive_symlink"),
        File {
          path: PathBuf::from("executable_file"),
          is_executable: true,
        },
      )),
      Some(PathStat::dir(
        PathBuf::from("dir_symlink"),
        Dir(PathBuf::from("dir")),
      )),
      None,
      None,
    ];
    assert_eq!(v, path_stats);
  }

  fn assert_only_file_is_executable(path: &Path, want_is_executable: bool) {
    let fs = new_posixfs(path);
    let stats = fs.scandir(&Dir(PathBuf::from("."))).wait().unwrap();
    assert_eq!(stats.0.len(), 1);
    match stats.0.get(0).unwrap() {
      &super::Stat::File(File {
        is_executable: got, ..
      }) => assert_eq!(want_is_executable, got),
      other => panic!("Expected file, got {:?}", other),
    }
  }

  fn new_posixfs<P: AsRef<Path>>(dir: P) -> PosixFS {
    PosixFS::new(
      dir.as_ref(),
      Arc::new(ResettablePool::new("test-pool-".to_string())),
      &[],
    ).unwrap()
  }
}
