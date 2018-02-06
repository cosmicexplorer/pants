# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
import re
import shutil
from contextlib import contextmanager

from pex.interpreter import PythonInterpreter

from pants.backend.python.subsystems.python_native_toolchain import PythonNativeToolchain, SandboxedInterpreter
from pants.backend.python.tasks.pex_build_util import is_local_python_dist
from pants.backend.python.tasks.setup_py import SetupPyRunner
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.task.task import Task
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property


PANTSSETUP_IMPORT_BOILERPLATE = """
# DO NOT EDIT THIS FILE -- AUTOGENERATED BY PANTS
# Target: {setup_target}

from distutils.core import Extension

def find_external_modules():
  return [Extension(str('native'), [{native_sources_joined}])]
"""


class BuildLocalPythonDistributions(Task):
  """Create python distributions (.whl) from python_dist targets."""

  options_scope = 'python-create-distributions'
  PYTHON_DISTS = 'user_defined_python_dists'

  @classmethod
  def product_types(cls):
    return [cls.PYTHON_DISTS]

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)

  @classmethod
  def implementation_version(cls):
    return super(BuildLocalPythonDistributions, cls).implementation_version() + [('BuildLocalPythonDistributions', 1)]

  @classmethod
  def subsystem_dependencies(cls):
    return super(BuildLocalPythonDistributions, cls).subsystem_dependencies() + (PythonNativeToolchain.Factory.scoped(cls),)

  @classmethod
  def register_options(cls, register):
    super(BuildLocalPythonDistributions, cls).register_options(register)
    register('--an-option', default='wow')

  @memoized_property
  def python_native_toolchain(self):
    return PythonNativeToolchain.Factory.scoped_instance(self).create()

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    self.context.log.debug('an_option: {}'.format(self.context.options.for_scope(self.options_scope).an_option))

    dist_targets = self.context.targets(is_local_python_dist)
    built_dists = set()

    if dist_targets:
      with self.invalidated(dist_targets,
                            fingerprint_strategy=DefaultFingerprintStrategy(),
                            invalidate_dependents=True) as invalidation_check:
        for vt in invalidation_check.all_vts:
          if vt.valid:
            self.context.log.debug('(valid) vt: {}'.format(repr(vt)))
            built_dists.add(self._get_whl_from_dir(os.path.join(vt.results_dir, 'dist')))
          else:
            self.context.log.debug('(invalid) vt: {}'.format(repr(vt)))
            if vt.target.dependencies :
              raise TargetDefinitionException(
                vt.target, 'The `dependencies` field is disallowed on `python_dist` targets. List any 3rd '
                           'party requirements in the install_requirements argument of your setup function.'
              )
            built_dists.add(self._create_dist(vt.target, vt.results_dir))

    self.context.log.info('built_dists: {}'.format(built_dists))

    self.context.products.register_data(self.PYTHON_DISTS, built_dists)

  def _copy_sources(self, dist_tgt, dist_target_dir):
    # Copy sources and setup.py over to vt results directory for packaging.
    # NB: The directory structure of the destination directory needs to match 1:1
    # with the directory structure that setup.py expects.
    all_sources = list(dist_tgt.sources_relative_to_target_base())
    self.context.log.info('all_sources: {}'.format(all_sources))
    for src_relative_to_target_base in all_sources:
      src_rel_to_results_dir = os.path.join(dist_target_dir, src_relative_to_target_base)
      safe_mkdir(os.path.dirname(src_rel_to_results_dir))
      abs_src_path = os.path.join(get_buildroot(),
                                  dist_tgt.address.spec_path,
                                  src_relative_to_target_base)
      shutil.copyfile(abs_src_path, src_rel_to_results_dir)

  def _create_dist(self, dist_tgt, dist_target_dir):
    """Create a .whl file for the specified python_distribution target."""
    self.context.log.info('dist_target_dir: {}'.format(dist_target_dir))
    interpreter = self.context.products.get_data(PythonInterpreter)
    sandboxed_interpreter = SandboxedInterpreter(
      self.python_native_toolchain.llvm_toolchain_dir(), interpreter)
    self._copy_sources(dist_tgt, dist_target_dir)
    # Build a whl using SetupPyRunner and return its absolute path.
    setup_runner = SetupPyRunner(dist_target_dir, 'bdist_wheel', interpreter=sandboxed_interpreter)
    # setup_runner = SetupPyRunner(dist_target_dir, 'bdist_wheel', interpreter=interpreter)
    setup_runner.run()
    return self._get_whl_from_dir(os.path.join(dist_target_dir, 'dist'))

  def _get_whl_from_dir(self, install_dir):
    """Return the absolute path of the whl in a setup.py install directory."""
    dists = glob.glob(os.path.join(install_dir, '*.whl'))
    if len(dists) == 0:
      raise TaskError('No distributions were produced by python_create_distribution task.')
    if len(dists) > 1:
      raise TaskError('Ambiguous local python distributions found: %s' % (' '.join(dists)))
    return dists[0]
