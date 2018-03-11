# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from textwrap import dedent

from pants.binaries.binary_util import BinaryUtil
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestBinaryUtilIntegration(PantsRunIntegrationTest):

  @classmethod
  def hermetic(cls):
    return True

  def test_no_baseurls_env(self):
    pants_run = self.run_pants([
      'gen.protoc',
      '--import-from-root',
      'testprojects/src/protobuf/org/pantsbuild/testproject/import_from_buildroot/bar',
    ], extra_env={
      'PANTS_BINARIES_BASEURLS': '[]',
    })
    self.assert_failure(pants_run)
    self.assertIn('No urls are defined for the --binaries-baseurls option.',
                  pants_run.stdout_data)

  def test_no_baseurls_cmdline(self):
    pants_run = self.run_pants([
      '--binaries-baseurls=[]',
      'gen.protoc',
      '--import-from-root',
      'testprojects/src/protobuf/org/pantsbuild/testproject/import_from_buildroot/bar',
    ])
    self.assert_failure(pants_run)
    self.assertIn('No urls are defined for the --binaries-baseurls option.',
                  pants_run.stdout_data)

  def test_no_baseurls_config(self):
    with self.gen_config_ini("""
    [GLOBAL]
    binaries_baseurls: []
    """) as config_path:
      pants_run = self.run_pants([
        '--pants-config-files={}'.format(config_path),
        'gen.protoc',
        '--import-from-root',
        'testprojects/src/protobuf/org/pantsbuild/testproject/import_from_buildroot/bar',
      ], extra_env={
        'PANTS_BINARIES_BASEURLS': '[]',
      })
      self.assert_failure(pants_run)
      self.assertIn('No urls are defined for the --binaries-baseurls option.',
                  pants_run.stdout_data)
