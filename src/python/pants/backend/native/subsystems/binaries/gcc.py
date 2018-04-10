# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.native_build_environment import NativeBuildEnvironment, NativeToolchainComponentMixin
from pants.binaries.binary_tool import NativeTool


class GCC(NativeTool, NativeToolchainComponentMixin):
  options_scope = 'gcc'
  default_version = '7.3.0'
  archive_type = 'tgz'

  def get_config(self):
    gcc_exe_path = os.path.join(self.select(), 'bin', 'gcc')
    return NativeBuildEnvironment.create_from_compiler_invocation(gcc_exe_path)
