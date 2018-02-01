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

from pants.backend.python.tasks.pex_build_util import is_local_python_dist
from pants.backend.python.tasks.setup_py import SetupPyRunner
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.task.task import Task
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir


PANTSSETUP_IMPORT_BOILERPLATE = """
# DO NOT EDIT THIS FILE -- AUTOGENERATED BY PANTS
# Target: {setup_target}

from distutils.core import Extension

def find_external_modules():
  return [Extension('native', [{native_sources_joined}])]
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

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    dist_targets = self.context.targets(is_local_python_dist)
    built_dists = set()

    if dist_targets:
      with self.invalidated(dist_targets,
                            fingerprint_strategy=DefaultFingerprintStrategy(),
                            invalidate_dependents=True) as invalidation_check:
        for vt in invalidation_check.all_vts:
          if vt.valid:
            built_dists.add(self._get_whl_from_dir(os.path.join(vt.results_dir, 'dist')))
          else:
            if vt.target.dependencies :
              raise TargetDefinitionException(
                vt.target, 'The `dependencies` field is disallowed on `python_dist` targets. List any 3rd '
                           'party requirements in the install_requirements argument of your setup function.'
              )
            built_dists.add(self._create_dist(vt.target, vt.results_dir))

    self.context.products.register_data(self.PYTHON_DISTS, built_dists)

  @contextmanager
  def _with_copied_sources_gen_pantssetup_pythonpath(self, dist_tgt, dist_target_dir):
    # Copy sources and setup.py over to vt results directory for packaging.
    # NB: The directory structure of the destination directory needs to match 1:1
    # with the directory structure that setup.py expects.
    py_sources = list(dist_tgt.sources_relative_to_target_base())
    native_sources = list(dist_tgt.cpp_sources_relative_to_target_base())
    all_sources = py_sources + native_sources
    for src_relative_to_target_base in all_sources:
      src_rel_to_results_dir = os.path.join(dist_target_dir, src_relative_to_target_base)
      safe_mkdir(os.path.dirname(src_rel_to_results_dir))
      abs_src_path = os.path.join(get_buildroot(),
                                  dist_tgt.address.spec_path,
                                  src_relative_to_target_base)
      shutil.copyfile(abs_src_path, src_rel_to_results_dir)
    with temporary_dir() as tmpdir:
      native_sources_joined = ','.join("'{}'".format(x) for x in native_sources)
      pantssetup_import_contents = PANTSSETUP_IMPORT_BOILERPLATE.format(
        setup_target=repr(dist_tgt),
        native_sources_joined=native_sources_joined)

      self.context.log.info(pantssetup_import_contents)

      pantssetup_module_path = os.path.join(tmpdir, 'pantssetup.py')
      with open(pantssetup_module_path, 'w') as pantssetup_module_fh:
        pantssetup_module_fh.write(pantssetup_import_contents)

      prev_pypath = os.environ.get('PYTHONPATH')
      if prev_pypath is None:
        new_pypath = tmpdir
      else:
        scrubbed_pypath = re.sub(':$', '', prev_pypath)
        new_pypath = '{}:{}'.format(scrubbed_pypath, tmpdir)

      with environment_as(PYTHONPATH=new_pypath):
        yield

  def _create_dist(self, dist_tgt, dist_target_dir):
    """Create a .whl file for the specified python_distribution target."""
    interpreter = self.context.products.get_data(PythonInterpreter)
    with self._with_copied_sources_gen_pantssetup_pythonpath(dist_tgt, dist_target_dir):
      # Build a whl using SetupPyRunner and return its absolute path.
      setup_runner = SetupPyRunner(dist_target_dir, 'bdist_wheel', interpreter=interpreter)
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
