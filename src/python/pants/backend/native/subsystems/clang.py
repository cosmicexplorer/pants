# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.subsystems.compiler import Compiler
from pants.binaries.binary_tool import ExecutablePathProvider, NativeTool
from pants.util.memo import memoized_property
from pants.util.process_handler import subprocess


class Clang(NativeTool, ExecutablePathProvider, Compiler):
  options_scope = 'clang'
  default_version = '6.0.0'
  archive_type = 'tgz'

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  @memoized_property
  def _cpp_compiler_path(self):
    return os.path.join(self.select(), 'bin', 'clang++')

  def compile_cpp(self, outdir, src_file_paths):
    with self.compile_environment(outdir, src_file_paths):
      argv = [self._cpp_compiler_path, '-c'] + src_file_paths
      return subprocess.check_output(argv=argv)
