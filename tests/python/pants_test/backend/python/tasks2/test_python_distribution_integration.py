# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.util.process_handler import subprocess
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonDistributionIntegrationTest(PantsRunIntegrationTest):
  # The paths to both a project containing a simple C extension (to be packaged into a
  # whl by setup.py) and an associated test to be consumed by the pants goals tested below.
  superhello_project = 'examples/src/python/example/python_distribution/hello/superhello'
  superhello_tests = 'examples/tests/python/example/python_distribution/hello/test_superhello'
  superhello_testprojects_project = 'testprojects/src/python/python_targets/python_distribution/superhello'

  def test_pants_binary(self):
    command=['binary', '{}:main'.format(self.superhello_project)]
    pants_run_27 = self.run_pants(command=command)
    self.assert_success(pants_run_27)
    # Check that the pex was built.
    pex = os.path.join(get_buildroot(), 'dist', 'main.pex')
    self.assertTrue(os.path.isfile(pex))
    # Check that the pex runs.
    output = subprocess.check_output(pex)
    self.assertIn('Super hello', output)
    # Cleanup
    os.remove(pex)

  def test_pants_run(self):
    command=['run', '{}:main'.format(self.superhello_project)]
    pants_run_27 = self.run_pants(command=command)
    self.assert_success(pants_run_27)
    # Check that text was properly printed to stdout.
    self.assertIn('Super hello', pants_run_27.stdout_data)

  def test_pants_test(self):
    command=['test', '{}:superhello'.format(self.superhello_tests)]
    pants_run_27 = self.run_pants(command=command)
    self.assert_success(pants_run_27)

  def test_with_conflicting_deps(self):
    command=['run', '{}:main_with_conflicting_dep'.format(self.superhello_project)]
    pants_run_27 = self.run_pants(command=command)
    self.assert_failure(pants_run_27)
    self.assertIn('Exception message: Could not satisfy all requirements', pants_run_27.stderr_data)
    command=['binary', '{}:main_with_conflicting_dep'.format(self.superhello_project)]
    pants_run_27 = self.run_pants(command=command)
    self.assert_failure(pants_run_27)
    self.assertIn('Exception message: Could not satisfy all requirements', pants_run_27.stderr_data)

  def test_pants_binary_with_two_targets(self):
    # Test that targets with unique python_dist dependencies only build with their specific
    # listed python_dist dependencies (i.e. that built dist products are filtered properly).
    command=['binary', '{}:main'.format(self.superhello_project), '{}:bin_with_python_dist'.format(self.superhello_testprojects_project)]
    pants_run_27 = self.run_pants(command=command)
    self.assert_success(pants_run_27)
    # Check that the pex was built.
    pex = os.path.join(get_buildroot(), 'dist', 'main.pex')
    self.assertTrue(os.path.isfile(pex))
    # Check that the pex runs.
    output = subprocess.check_output(pex)
    self.assertIn('Super hello', output)
    # Check that the pex was built.
    pex2 = os.path.join(get_buildroot(), 'dist', 'bin_with_python_dist.pex')
    self.assertTrue(os.path.isfile(pex2))
    # Check that the pex runs.
    output = subprocess.check_output(pex2)
    self.assertIn('A different Super hello', output)
    # Cleanup
    os.remove(pex)
    os.remove(pex2)
