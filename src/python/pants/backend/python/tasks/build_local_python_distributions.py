# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import glob
import os
import re
import shutil
from future.utils import text_type

from pex import pep425tags
from pex.interpreter import PythonInterpreter

from pants.backend.native.config.environment import LLVMCppToolchain, LLVMCToolchain, Platform
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.native.tasks.link_shared_libraries import SharedLibrary
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.python_native_code import (PythonNativeCode,
                                                                SetupPyExecutionEnvironment,
                                                                SetupPyNativeTools,
                                                                ensure_setup_requires_site_dir)
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks.pex_build_util import is_local_python_dist
from pants.backend.python.tasks.setup_py import SetupPyRunner
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.build_graph.address import Address
from pants.task.task import Task
from pants.util.collections import assert_single_element
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdir_for, split_basename_and_dirname
from pants.util.memo import memoized_classproperty, memoized_property
from pants.util.objects import datatype


class LocalPythonDistributionWheel(datatype([('path', text_type)])): pass


class BuildLocalPythonDistributions(Task):
  """Create python distributions (.whl) from python_dist targets."""

  options_scope = 'python-create-distributions'

  cache_target_dirs = True

  # NB: these are all the immediate subdirectories of the target's results directory.
  # This contains any modules from a setup_requires().
  _SETUP_REQUIRES_SITE_SUBDIR = 'setup_requires_site'
  # This will contain the sources used to build the python_dist().
  _DIST_SOURCE_SUBDIR = 'python_dist_subdir'

  # This defines the output directory when building the dist, so we know where the output wheel is
  # located. It is a subdirectory of `_DIST_SOURCE_SUBDIR`.
  _DIST_OUTPUT_DIR = 'dist'

  @classmethod
  def product_types(cls):
    return [LocalPythonDistributionWheel]

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)
    round_manager.require(SharedLibrary)

  @classmethod
  def implementation_version(cls):
    return super(BuildLocalPythonDistributions, cls).implementation_version() + [('BuildLocalPythonDistributions', 3)]

  @classmethod
  def subsystem_dependencies(cls):
    return super(BuildLocalPythonDistributions, cls).subsystem_dependencies() + (
      PythonNativeCode.scoped(cls),
    )

  class BuildLocalPythonDistributionsError(TaskError): pass

  @memoized_classproperty
  def _platform(cls):
    return Platform.create()

  @memoized_property
  def _python_native_code_settings(self):
    return PythonNativeCode.scoped_instance(self)

  # FIXME(#5869): delete this and get Subsystems from options, when that is possible.
  def _request_single(self, product, subject):
    # NB: This is not supposed to be exposed to Tasks yet -- see #4769 to track the status of
    # exposing v2 products in v1 tasks.
    return self.context._scheduler.product_request(product, [subject])[0]

  @memoized_property
  def _c_toolchain(self):
    llvm_c_toolchain = self._request_single(
      LLVMCToolchain, self._python_native_code_settings.native_toolchain)
    return llvm_c_toolchain.c_toolchain

  @memoized_property
  def _cpp_toolchain(self):
    llvm_cpp_toolchain = self._request_single(
      LLVMCppToolchain, self._python_native_code_settings.native_toolchain)
    return llvm_cpp_toolchain.cpp_toolchain

  def _get_setup_requires_to_resolve(self, dist_target):
    if not dist_target.setup_requires:
      return None

    reqs_to_resolve = set()

    for setup_req_lib_addr in dist_target.setup_requires:
      for req_lib in self.context.build_graph.resolve(setup_req_lib_addr):
        for req in req_lib.requirements:
          reqs_to_resolve.add(req)

    if not reqs_to_resolve:
      return None

    return reqs_to_resolve

  @classmethod
  def _get_output_dir(cls, results_dir):
    return os.path.join(results_dir, cls._DIST_SOURCE_SUBDIR)

  @classmethod
  def _get_dist_dir(cls, results_dir):
    return os.path.join(cls._get_output_dir(results_dir), cls._DIST_OUTPUT_DIR)

  def execute(self):
    dist_targets = self.context.targets(is_local_python_dist)

    if dist_targets:
      interpreter = self.context.products.get_data(PythonInterpreter)
      shared_libs_product = self.context.products.get(SharedLibrary)

      with self.invalidated(dist_targets, invalidate_dependents=True) as invalidation_check:
        for vt in invalidation_check.invalid_vts:
          self._prepare_and_create_dist(interpreter, shared_libs_product, vt)

        local_wheel_product = self.context.products.get(LocalPythonDistributionWheel)
        for vt in invalidation_check.all_vts:
          wheel_dist_path = self._get_whl_from_dir(vt.results_dir)
          local_wheel_product.append_to_target_base(
            vt.target,
            LocalPythonDistributionWheel(text_type(wheel_dist_path)))

  def _get_native_artifact_deps(self, target):
    native_artifact_targets = []
    if target.dependencies:
      for dep_tgt in target.dependencies:
        if not NativeLibrary.produces_ctypes_native_library(dep_tgt):
          raise TargetDefinitionException(
            target,
            "Target '{}' is invalid: the only dependencies allowed in python_dist() targets "
            "are C or C++ targets with a ctypes_native_library= kwarg."
            .format(dep_tgt.address.spec))
        native_artifact_targets.append(dep_tgt)
    return native_artifact_targets

  def _copy_sources(self, dist_tgt, dist_target_dir):
    # Copy sources and setup.py over to vt results directory for packaging.
    # NB: The directory structure of the destination directory needs to match 1:1
    # with the directory structure that setup.py expects.
    all_sources = list(dist_tgt.sources_relative_to_target_base())
    for src_relative_to_target_base in all_sources:
      src_rel_to_results_dir = os.path.join(dist_target_dir, src_relative_to_target_base)
      safe_mkdir_for(src_rel_to_results_dir)
      abs_src_path = os.path.join(get_buildroot(),
                                  dist_tgt.address.spec_path,
                                  src_relative_to_target_base)
      shutil.copyfile(abs_src_path, src_rel_to_results_dir)

  def _add_artifacts(self, dist_target_dir, shared_libs_product, native_artifact_targets):
    all_shared_libs = []
    for tgt in native_artifact_targets:
      product_mapping = shared_libs_product.get(tgt)
      base_dir = assert_single_element(product_mapping.keys())
      shared_lib = assert_single_element(product_mapping[base_dir])
      all_shared_libs.append(shared_lib)

    for shared_lib in all_shared_libs:
      basename = os.path.basename(shared_lib.path)
      # NB: We convert everything to .so here so that the setup.py can just
      # declare .so to build for either platform.
      resolved_outname = re.sub(r'\..*\Z', '.so', basename)
      dest_path = os.path.join(dist_target_dir, resolved_outname)
      safe_mkdir_for(dest_path)
      shutil.copyfile(shared_lib.path, dest_path)

    return all_shared_libs

  def _prepare_and_create_dist(self, interpreter, shared_libs_product, versioned_target):
    dist_target = versioned_target.target

    native_artifact_deps = self._get_native_artifact_deps(dist_target)

    results_dir = versioned_target.results_dir

    dist_output_dir = self._get_output_dir(results_dir)

    all_native_artifacts = self._add_artifacts(
      dist_output_dir, shared_libs_product, native_artifact_deps)

    is_platform_specific = False
    native_tools = None
    if self._python_native_code_settings.pydist_has_native_sources(dist_target):
      # We add the native tools if we need to compile code belonging to this python_dist() target.
      # TODO: test this branch somehow!
      native_tools = SetupPyNativeTools(
        c_toolchain=self._c_toolchain,
        cpp_toolchain=self._cpp_toolchain,
        platform=self._platform)
      # Native code in this python_dist() target requires marking the dist as platform-specific.
      is_platform_specific = True
    elif len(all_native_artifacts) > 0:
      # We are including a platform-specific shared lib in this dist, so mark it as such.
      is_platform_specific = True

    setup_requires_dir = os.path.join(results_dir, self._SETUP_REQUIRES_SITE_SUBDIR)
    setup_reqs_to_resolve = self._get_setup_requires_to_resolve(dist_target)
    if setup_reqs_to_resolve:
      self.context.log.debug('python_dist target(s) with setup_requires detected. '
                             'Installing setup requirements: {}\n\n'
                             .format([req.key for req in setup_reqs_to_resolve]))

    setup_requires_site_dir = ensure_setup_requires_site_dir(
      setup_reqs_to_resolve, interpreter, setup_requires_dir, platforms=['current'])
    if setup_requires_site_dir:
      self.context.log.debug('Setting PYTHONPATH with setup_requires site directory: {}'
                             .format(setup_requires_site_dir))

    setup_py_execution_environment = SetupPyExecutionEnvironment(
      setup_requires_site_dir=setup_requires_site_dir,
      setup_py_native_tools=native_tools)

    versioned_target_fingerprint = versioned_target.cache_key.hash

    self._create_dist(
      dist_target,
      dist_output_dir,
      interpreter,
      setup_py_execution_environment,
      versioned_target_fingerprint,
      is_platform_specific)

  # NB: "snapshot" refers to a "snapshot release", not a Snapshot.
  def _generate_snapshot_bdist_wheel_argv(self, snapshot_fingerprint, is_platform_specific):
    """Create a command line to pass to :class:`SetupPyRunner`.

    Note that distutils will convert `snapshot_fingerprint` into a string suitable for a version
    tag. Currently for versioned target fingerprints, this seems to convert all punctuation into
    '.' and downcase all ASCII chars. See https://www.python.org/dev/peps/pep-0440/ for further
    information on allowed version names.

    NB: adds a '+' before the fingerprint to the build tag!
    """
    egg_info_snapshot_tag_args = ['egg_info', '--tag-build=+{}'.format(snapshot_fingerprint)]
    bdist_whl_args = ['bdist_wheel']
    if is_platform_specific:
      platform_args = ['--plat-name', pep425tags.get_platform()]
    else:
      platform_args = []

    dist_dir_args = ['--dist-dir', self._DIST_OUTPUT_DIR]

    setup_py_command = egg_info_snapshot_tag_args + bdist_whl_args + platform_args + dist_dir_args
    return setup_py_command

  def _create_dist(self, dist_tgt, dist_target_dir, interpreter,
                   setup_py_execution_environment, snapshot_fingerprint, is_platform_specific):
    """Create a .whl file for the specified python_distribution target."""
    self._copy_sources(dist_tgt, dist_target_dir)

    setup_py_snapshot_version_argv = self._generate_snapshot_bdist_wheel_argv(
      snapshot_fingerprint, is_platform_specific)

    setup_runner = SetupPyRunner(
      source_dir=dist_target_dir,
      setup_command=setup_py_snapshot_version_argv,
      interpreter=interpreter)

    setup_py_env = setup_py_execution_environment.as_environment()
    with environment_as(**setup_py_env):
      # Build a whl using SetupPyRunner and return its absolute path.
      was_installed_successfully = setup_runner.run()
      # FIXME: Make a run_raising_error() method in SetupPyRunner that doesn't print directly to
      # stderr like pex does (better: put this in pex itself).
      if not was_installed_successfully:
        raise self.BuildLocalPythonDistributionsError(
          "Installation of python distribution from target {target} into directory {into_dir} "
          "failed.\n"
          "The chosen interpreter was: {interpreter}.\n"
          "The execution environment was: {env}.\n"
          "The setup command was: {command}."
          .format(target=dist_tgt,
                  into_dir=dist_target_dir,
                  interpreter=interpreter,
                  env=setup_py_env,
                  command=setup_py_snapshot_version_argv))

  @classmethod
  def _get_whl_from_dir(cls, install_dir):
    """Return the absolute path of the whl in a setup.py install directory."""
    dist_dir = cls._get_dist_dir(install_dir)
    dists = glob.glob(os.path.join(dist_dir, '*.whl'))
    if len(dists) == 0:
      raise cls.BuildLocalPythonDistributionsError(
        'No distributions were produced by python_create_distribution task.')
    if len(dists) > 1:
      # TODO: is this ever going to happen?
      raise cls.BuildLocalPythonDistributionsError('Ambiguous local python distributions found: {}'
                                                   .format(dists))
    return dists[0]
