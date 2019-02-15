# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os

from future.utils import text_type

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.tasks.classpath_products import ClasspathEntry
from pants.backend.native.config.environment import Platform
from pants.backend.native.subsystems.binaries.binutils import Binutils
from pants.backend.native.subsystems.binaries.gcc import GCC
from pants.backend.native.subsystems.xcode_cli_tools import XCodeCLITools
from pants.base.build_environment import get_buildroot, get_pants_cachedir
from pants.base.hash_utils import stable_json_sha1
from pants.base.workunit import WorkUnitLabel
from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.fs import Digest, DirectoryToMaterialize, PathGlobs, PathGlobsAndRoot
from pants.engine.isolated_process import ExecuteProcessRequest, ProcessExecutionFailure
from pants.java.distribution.distribution import Distribution
from pants.util.collections import assert_single_element
from pants.util.dirutil import fast_relpath, fast_relpath_optional
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import Exactly, TypedCollection, datatype
from pants.util.strutil import safe_shlex_join


logger = logging.getLogger(__name__)


def fast_relpath_collection(collection, root=get_buildroot()):
  return [fast_relpath_optional(c, root) or c for c in collection]


class GraalCEUrlGenerator(BinaryToolUrlGenerator):

  _DIST_URL_FMT = 'https://github.com/oracle/graal/releases/download/vm-{version}/{base}'
  _ARCHIVE_BASE_FMT = 'graalvm-ce-{version}-{system_id}-amd64.tar.gz'
  _SYSTEM_ID = {
    'mac': 'macos',
    'linux': 'linux',
  }

  def generate_urls(self, version, host_platform):
    system_id = self._SYSTEM_ID[host_platform.os_name]
    archive_basename = self._ARCHIVE_BASE_FMT.format(version=version, system_id=system_id)
    return [self._DIST_URL_FMT.format(version=version, base=archive_basename)]


class GraalCE(NativeTool, JvmToolMixin):

  options_scope = 'graal'
  default_version = '1.0.0-rc12'
  archive_type = 'tgz'

  def get_external_url_generator(self):
    return GraalCEUrlGenerator()

  @classmethod
  def register_options(cls, register):
    super(GraalCE, cls).register_options(register)
    register('--report-unsupported-elements', type=bool, default=True, fingerprint=True,
             advanced=True,
             # TODO: this is plagiarized directly from `native-image --help`!
             help='Whether to report usage of unsupported methods and fields at run time when '
                  'accessed for the first time, instead of as an error during image building.')

  @memoized_property
  def _report_unsupported_elements(self):
    return self.get_options().report_unsupported_elements

  @classmethod
  def subsystem_dependencies(cls):
    return super(GraalCE, cls).subsystem_dependencies() + (
      Binutils.scoped(cls),
      GCC.scoped(cls),
      XCodeCLITools.scoped(cls),
    )

  @memoized_method
  def _snapshot_everything_under(self, scheduler, base_dir):
    glob_it_all = PathGlobsAndRoot(PathGlobs(['**/*']), base_dir)
    everything_snapshot = assert_single_element(scheduler.capture_snapshots(tuple([glob_it_all])))
    return everything_snapshot

  def _binutils_install(self, scheduler):
    return self._snapshot_everything_under(scheduler, Binutils.scoped_instance(self).select())

  def _gcc_install(self, scheduler):
    return self._snapshot_everything_under(scheduler, GCC.scoped_instance(self).select())

  def _xcode_cli_tools_install(self, scheduler):
    cpp_compiler = XCodeCLITools.scoped_instance(self).cpp_compiler()
    bin_dirs = cpp_compiler.path_entries
    lib_dirs = cpp_compiler.library_dirs
    include_dirs = cpp_compiler.include_dirs

    # Attempt to capture snapshots which would put each directory at the top level of the sandbox.
    all_globs_with_roots = []
    for resource_dir in bin_dirs + lib_dirs + include_dirs:
      containing_dir = os.path.dirname(resource_dir)
      directory_basename = os.path.basename(resource_dir)
      globs_with_dir = PathGlobsAndRoot(PathGlobs(['{}/**/*'.format(directory_basename)]),
                                        containing_dir)
      all_globs_with_roots.append(globs_with_dir)

    # System/Library/Frameworks/CoreFoundation.framework/Versions/A/Headers/CoreFoundation.h
    framework_glob = 'System/Library/Frameworks/CoreFoundation.framework/Versions/A/Headers/*'
    framework_dir = '/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk'
    all_globs_with_roots.append(PathGlobsAndRoot(PathGlobs([framework_glob]), framework_dir))

    all_snapshots = scheduler.capture_snapshots(tuple(all_globs_with_roots))
    return all_snapshots

  _FINAL_PATH_COMPONENTS = {
    'mac': ['Contents', 'home'],
    'linux': [],
  }

  @memoized_method
  def select(self):
    unpacked_base_path = super(GraalCE, self).select()
    return os.path.join(
      unpacked_base_path,
      'graalvm-ce-{}'.format(self.version()),
      *self._FINAL_PATH_COMPONENTS[self.host_platform.os_name])

  @memoized_property
  def bin_dir(self):
    return os.path.join(self.select(), 'bin')

  @memoized_property
  def runtime_jar(self):
    return os.path.join(self.select(), 'jre/lib/rt.jar')

  @memoized_method
  def runtime_jar_cp_entry(self, scheduler):
    rel_path = 'jre/lib/rt.jar'
    globs_with_root = PathGlobsAndRoot(PathGlobs([rel_path]), self.select())
    snapshot = assert_single_element(scheduler.capture_snapshots(tuple([globs_with_root])))
    return ClasspathEntry(rel_path, snapshot)

  @memoized_method
  def _native_image_exe(self, scheduler):
    rel_path = 'bin/native-image'
    image_real_path = os.path.realpath(os.path.join(self.select(), rel_path))
    real_rel_path = fast_relpath(image_real_path, self.select())
    globs_with_root = PathGlobsAndRoot(PathGlobs(['**/*']), self.select())
    everything_snapshot = assert_single_element(scheduler.capture_snapshots(
      tuple([globs_with_root])))
    return (real_rel_path, everything_snapshot)

  @memoized_property
  def _cache_dir(self):
    return os.path.join(get_pants_cachedir(), 'graal-images')

  class GraalNativeImageConfiguration(datatype([
      ('extra_build_cp', TypedCollection(Exactly(ClasspathEntry))),
      ('digests', TypedCollection(Exactly(Digest))),
      # Relative paths to resources within entries in `extra_build_cp`.
      ('substitution_resources_paths', TypedCollection(Exactly(text_type))),
      ('reflection_resources_paths', TypedCollection(Exactly(text_type))),
      'context',
  ])):

    # TODO: this shouldn't be dependent on the directory digests, but on the invalidation hashes of
    # the dependent targets! Otherwise it gets remade after a clean-all!!
    @property
    def fingerprint(self):
      return stable_json_sha1(
        tuple(repr(cp.directory_digest.directory_digest) for cp in self.extra_build_cp)
        + tuple(repr(d) for d in self.digests)
        + self.substitution_resources_paths
        + self.reflection_resources_paths
      )

  class _GraalDist(Distribution):

    def find_libs_path_globs(self, names):
      libs_abs = self.find_libs(names)
      libs_rel = fast_relpath_collection(libs_abs, root=self.home)
      path_globs = PathGlobsAndRoot(
        PathGlobs(tuple(libs_rel)),
        self.home)
      return (libs_rel, path_globs)

  @memoized_property
  def graal_dist(self):
    return self._GraalDist(home_path=self.select())

  class NativeImageCreationError(Exception): pass

  @memoized_method
  def _snapshot_native_image(self, scheduler, fingerprinted_native_image_path):
    """Snapshot the produced native image for use in hermetic execution."""
    image_relpath = fast_relpath(fingerprinted_native_image_path, self._cache_dir)
    globs_with_root = PathGlobsAndRoot(PathGlobs([image_relpath]), self._cache_dir)
    snapshot = assert_single_element(scheduler.capture_snapshots(tuple([globs_with_root])))
    return snapshot

  @memoized_method
  def _memoized_classpath_entries_with_digests(self, classpath_paths, scheduler,
                                               root=get_buildroot()):
    snapshots = scheduler.capture_snapshots(tuple(
      PathGlobsAndRoot(PathGlobs([path]), root)
      for path in fast_relpath_collection(classpath_paths, root)
    ))
    logger.debug('snapshots: {}'.format(snapshots))
    return [ClasspathEntry(path, snapshot) for path, snapshot in list(zip(classpath_paths, snapshots))]

  # _JDK_LIB_NAMES = ['rt.jar', 'dt.jar', 'jce.jar', 'tools.jar']
  _JDK_LIB_NAMES = ['rt.jar']

  def produce_native_image(self, tool_classpath, main_class, build_config, jvm_options):
    context = build_config.context
    scheduler = context._scheduler

    input_hash = stable_json_sha1([
      build_config.fingerprint,
      self._report_unsupported_elements,
    ] + jvm_options)
    output_image_file_name = '{}-{}'.format(main_class, input_hash)

    # If the image already exists, just snapshot it and pass it on.
    fingerprinted_native_image_path = os.path.join(self._cache_dir, output_image_file_name)
    if os.path.isfile(fingerprinted_native_image_path):
      return (
        self.graal_dist,
        output_image_file_name,
        self._snapshot_native_image(scheduler, fingerprinted_native_image_path).directory_digest,
      )

    tool_cp_entries = (
      self._memoized_classpath_entries_with_digests(tuple(tool_classpath), scheduler)
      + list(build_config.extra_build_cp)
    )
    native_image_exe, image_snap = self._native_image_exe(scheduler)

    all_digests = (
      build_config.digests
      + tuple(cp.directory_digest.directory_digest for cp in tool_cp_entries)
      + tuple([
        image_snap.directory_digest,
        # native-image needs gcc (specifically) and a linker and assembler (on Linux) to build
        # things.
        self._gcc_install(scheduler).directory_digest,
      ] + Platform.create().resolve_for_enum_variant({
        'darwin': lambda: [
          snap.directory_digest
          for snap in self._xcode_cli_tools_install(scheduler)
        ],
        # TODO: use the NativeToolchain to get the appropriate linker?
        'linux': lambda: [self._binutils_install(scheduler).directory_digest],
      })())
    )
    merged_digest = scheduler.merge_directories(all_digests)

    # Otherwise, build it with a remotable process execution.
    argv = [
      native_image_exe,
      '-classpath', ':'.join([cp.path for cp in tool_cp_entries]),
      '--verbose',
      '--enable-all-security-services',
      '--allow-incomplete-classpath',
      # This is suggested when you see an error.
      '-H:+ReportExceptionStackTraces',
      # NB: Using a single thread during native image generation makes the stacktraces actually
      # match the errors.
      '-H:NumberOfThreads=8',
      '--no-server',
      '--tool:truffle',
      # TODO: make this -O9!
      '-O0',
    ] + [
      '-J{}'.format(opt) for opt in jvm_options
    ] + [
      '-H:Class={}'.format(main_class),
    ] + (
      ['--report-unsupported-elements-at-runtime'] if self._report_unsupported_elements else []
    ) + [
      '-H:Name={}'.format(output_image_file_name),
    ] + ([
      '-H:SubstitutionResources={}'
      .format(','.join(build_config.substitution_resources_paths))
    ] if build_config.substitution_resources_paths else []) + ([
      '-H:ReflectionConfigurationResources={}'
      .format(','.join(build_config.reflection_resources_paths))
    ] if build_config.reflection_resources_paths else [])

    # TODO: this fails on osx, it needs _stdio.h! This can probably be fixed by adding XCodeCLITools
    # to it, or something.
    req = ExecuteProcessRequest(
      # TODO: /bin/sh is still breaking isolation a bit, even if we use it in testing.
      argv=tuple([
        '/bin/sh',
        '-c',
        ' ; '.join([
          '([[ -f bin/cc ]] || /bin/ln -s gcc bin/cc)',
          # TODO: native-image complains about not being able to find
          # CoreFoundation/CoreFoundation.h, which isn't even a path that exists (no CoreFoundation
          # dir exists), so we have to make a directory named that, and stick it in the root of the
          # sandbox so native-image can pick it up.
          """\
/bin/mkdir -p CoreFoundation && \
/bin/cp System/Library/Frameworks/CoreFoundation.framework/Versions/A/Headers/* CoreFoundation/""",
          'PATH=$(pwd)/bin:$PATH CPATH=$(pwd) {}'.format(safe_shlex_join(argv))
        ]),
      ]),
      input_files=merged_digest,
      description='graal native-image for {}'.format(main_class),
      output_files=tuple([output_image_file_name]),
      jdk_home=self.graal_dist.home,
    )
    logger.debug('req: {}'.format(req))
    try:
      res = context.execute_process_synchronously_or_raise(
        req, 'graal-native-image-create', [WorkUnitLabel.COMPILER])
    except ProcessExecutionFailure as e:
      raise self.NativeImageCreationError('error creating graal native-image for {}: {}'
                                          .format(main_class, e))

    # Make the image exist!
    scheduler.materialize_directories(tuple([
      DirectoryToMaterialize(self._cache_dir, res.output_directory_digest),
    ]))

    return (self.graal_dist, output_image_file_name, res.output_directory_digest)
