# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from google.cloud import bigquery
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


# TODO: ???/explain how you as a user can write pants integration tests, e.g. for binaries you want
# to make sure work in CI.
class TestBigqueryPythonRun(PantsRunIntegrationTest):

  @classmethod
  def hermetic(cls):
    return True

  # TODO: is this test definitely run in CI?
  def test_bigquery_python_run(self):
    pants_run = self.do_command(
      "--python-setup-interpreter-constraints=['CPython>=2.7,<3']",
      'run',
      'examples/tests/python/example_test/pkg_resources_access:bin',
    )
    # Using `-q` in self.do_command() doesn't appear to be making pants run quietly here, but we can
    # rely on the output containing exactly this line.
    self.assertIn('\nbigquery, version {}\n'.format(bigquery.__version__),
                  pants_run.stdout_data)
