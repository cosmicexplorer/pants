// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

mod communication;
mod mmap_bindings;
mod pants_vcfs_interface;
mod shm;

use ::fs::{File, GlobExpansionConjunction, PathGlobs, PathStat, StrictGlobMatching};

use futures01::{future, Future};
use parking_lot::{Mutex, RwLock};

use std::env;
use std::fs;
use std::io;
use std::ops::Deref;
use std::path::PathBuf;
use std::str;
use std::sync::{
  atomic::{AtomicU32, Ordering},
  Arc,
};

#[derive(Debug)]
pub enum VcfsError {
  S(String),
  Encoding(str::Utf8Error),
  Io(io::Error),
  Shm(shm::ShmError),
  Comm(communication::CommunicationError),
}

pub type Error = VcfsError;

impl From<String> for VcfsError {
  fn from(err: String) -> Self {
    VcfsError::S(err)
  }
}

impl From<str::Utf8Error> for VcfsError {
  fn from(err: str::Utf8Error) -> Self {
    VcfsError::Encoding(err)
  }
}

impl From<io::Error> for VcfsError {
  fn from(err: io::Error) -> Self {
    VcfsError::Io(err)
  }
}

impl From<shm::ShmError> for VcfsError {
  fn from(err: shm::ShmError) -> Self {
    VcfsError::Shm(err)
  }
}

impl From<communication::CommunicationError> for VcfsError {
  fn from(err: communication::CommunicationError) -> Self {
    VcfsError::Comm(err)
  }
}

#[derive(Clone)]
pub struct ShmHandleWrapper {
  shm_handle: Arc<RwLock<shm::ShmHandle>>,
}

impl ShmHandleWrapper {
  pub fn new(shm_handle: shm::ShmHandle) -> Self {
    ShmHandleWrapper {
      shm_handle: Arc::new(RwLock::new(shm_handle)),
    }
  }
}

impl Deref for ShmHandleWrapper {
  type Target = Arc<RwLock<shm::ShmHandle>>;

  fn deref(&self) -> &Self::Target {
    &self.shm_handle
  }
}

/* TODO: why doesn't Arc<RwLock<>> do this for us automatically?? */
unsafe impl Send for ShmHandleWrapper {}
unsafe impl Sync for ShmHandleWrapper {}

pub struct VcfsInstance {
  message_id_counter: AtomicU32,
  executor: task_executor::Executor,
  vcfs_client: Arc<Mutex<communication::VcfsClient>>,
  shm_handle: ShmHandleWrapper,
}

impl VcfsInstance {
  pub fn new(executor: task_executor::Executor, root: PathBuf) -> Result<Self, VcfsError> {
    /* Assert that the given git root is an existing directory. */
    assert!(fs::metadata(&root)?.is_dir());

    /* We assume that we are being run from the buildroot, which is equivalent to the git root. */
    assert_eq!(
      fs::canonicalize(env::current_dir()?)?,
      fs::canonicalize(&root)?,
    );

    let message_id_counter = AtomicU32::new(0);

    /* let socket_path = root.join(".vcfs-socket="); */
    let socket_path = PathBuf::from("/Users/dmcclanahan/workspace/.vcfs-socket");
    let vcfs_client = communication::VcfsClient::from_socket_path(&socket_path)?;

    let shm_handle = shm::ShmHandle::new(
      1_000_003 as mmap_bindings::key_t,
      (4096 * 500000) as usize,
      shm::Permission::Read,
    )?;

    Ok(VcfsInstance {
      message_id_counter,
      executor,
      vcfs_client: Arc::new(Mutex::new(vcfs_client)),
      shm_handle: ShmHandleWrapper::new(shm_handle),
    })
  }

  fn extract_thrift_path_globs(path_globs: PathGlobs) -> pants_vcfs_interface::PathGlobs {
    let PathGlobs {
      exclude,
      strict_match_behavior,
      conjunction,
      patterns,
      ..
    } = path_globs;
    let include_patterns: Vec<String> = patterns
      .into_iter()
      .map(|p| p.as_str().to_string())
      .collect();
    let exclude_patterns: Vec<String> = exclude.exclude_patterns().into_iter().cloned().collect();
    let strictness = match strict_match_behavior {
      /* TODO: make use of the string provided for Error and Warn! */
      StrictGlobMatching::Error(_) => pants_vcfs_interface::StrictGlobMatching::Error,
      StrictGlobMatching::Warn(_) => pants_vcfs_interface::StrictGlobMatching::Warn,
      StrictGlobMatching::Ignore => pants_vcfs_interface::StrictGlobMatching::Ignore,
    };
    let conjunction = match conjunction {
      GlobExpansionConjunction::AllMatch => pants_vcfs_interface::Conjunction::AllMatch,
      GlobExpansionConjunction::AnyMatch => pants_vcfs_interface::Conjunction::AnyMatch,
    };
    pants_vcfs_interface::PathGlobs {
      include_patterns: Some(include_patterns),
      exclude_patterns: Some(exclude_patterns),
      strictness: Some(strictness),
      conjunction: Some(conjunction),
    }
  }

  fn create_expand_globs_message(
    &self,
    path_globs: pants_vcfs_interface::PathGlobs,
  ) -> pants_vcfs_interface::ExpandGlobsMessage {
    /* Get a unique id for the message. */
    let id = self.message_id_counter.fetch_add(1, Ordering::Relaxed);
    let message_id = pants_vcfs_interface::MessageId {
      /* A u32 can cleanly downnsize into an i64! */
      id: Some(id as i64),
    };
    pants_vcfs_interface::ExpandGlobsMessage {
      message_id: Some(message_id),
      path_globs: Some(path_globs),
    }
  }

  pub fn expand_globs(
    &self,
    path_globs: PathGlobs,
  ) -> impl Future<Item = Vec<PathStat>, Error = VcfsError> {
    let vcfs_client = self.vcfs_client.clone();
    let shm_handle = self.shm_handle.clone();

    let thrift_globs = Self::extract_thrift_path_globs(path_globs);
    let expand_globs_message = self.create_expand_globs_message(thrift_globs);

    let glob_expansion = future::lazy(move || {
      future::result(
        vcfs_client
          .lock()
          .do_expand_globs_call(expand_globs_message),
      )
    });

    let all_file_path_stats = glob_expansion.map(
      move |file_descriptors: Vec<pants_vcfs_interface::FileWithContentsDescriptor>| {
        /* TODO: parallelize/SIMDify this (with rayon??)?? see SIMDify crate? */
        let shm_handle = (*shm_handle).read();
        let file_contents: Vec<PathStat> = file_descriptors
          .into_iter()
          .map(|fd| {
            let shm::FileWithContents { path, .. } =
              shm::FileWithContents::from_shm_descriptor(&*shm_handle, &fd);
            /* FIXME: read the file contents into the Store too!!! */
            PathStat::File {
              path: path.to_path_buf(),
              stat: File {
                path: path.to_path_buf(),
                is_executable: false,
              },
            }
          })
          .collect();
        file_contents
      },
    );

    self
      .executor
      .spawn_on_io_pool(all_file_path_stats)
      .map_err(|e| e.into())
  }
}

#[cfg(test)]
mod tests {
  #[test]
  fn it_works() {
    assert_eq!(2 + 2, 4);
  }
}
