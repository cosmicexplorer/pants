# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from tempfile import mkdtemp

from pants.engine.fs import create_fs_rules
from pants.engine.rules import SingletonRule
from pants.backend.native.subsystems.clang import Clang
from pants.backend.native.rules.cpp_rules import Compiler, CppSources, CppObjOutputDir, CppObjects, create_cpp_rules
from pants.util.contextutil import environment_as, get_joined_path
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree
from pants.util.process_handler import subprocess
from pants_test.base_test import BaseTest
from pants_test.engine.scheduler_test_base import SchedulerTestBase
from pants_test.subsystem.subsystem_util import global_subsystem_instance


# TODO(cosmicexplorer): Can we have some form of this run in an OSX shard on
# Travis?
# FIXME(cosmicexplorer): We need to test gcc as well, but the gcc driver can't
# find the right include directories for system headers in Travis. We need to
# use the clang driver to find library paths, then use those when invoking gcc.
class TestNativeToolchain(BaseTest, SchedulerTestBase):

  def setUp(self):
    super(TestNativeToolchain, self).setUp()

    rules = create_fs_rules() + create_cpp_rules()

    self.clang = global_subsystem_instance(Clang)

    self.scheduler = self.mk_scheduler(rules=rules, work_dir=self.build_root)

  def test_hello_c(self):
    c_src = self.create_file('hello.c', contents="""
#include "stdio.h"

int main() {
  printf("%s\\n", "hello, world!");
}
""")

    c_dir = os.path.dirname(c_src)

    hello_objs = self.scheduler.product_request(
      CppObjects, [
        self.clang,
        CppSources(root_dir=c_dir,
                   file_paths=['hello.c']),
        CppObjOutputDir(dir_path=c_dir),
      ])

    raise Exception(repr(os.listdir(c_dir)))

    self._invoke_capturing_output(['clang', 'hello.c', '-o', 'hello_clang'])
    c_output = self._invoke_capturing_output(['./hello_clang'])
    self.assertEqual(c_output, 'hello, world!\n')

  def test_hello_cpp(self):
    self.create_file('hello.cpp', contents="""
#include <iostream>

int main() {
  std::cout << "hello, world!" << std::endl;
}
""")

    self._invoke_capturing_output(['clang++', 'hello.cpp', '-o', 'hello_clang++'])
    cpp_output = self._invoke_capturing_output(['./hello_clang++'])
    self.assertEqual(cpp_output, 'hello, world!\n')
