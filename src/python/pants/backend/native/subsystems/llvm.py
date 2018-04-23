# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import Linker, LinkerProvider
from pants.binaries.binary_tool import NativeTool


class LLVM(NativeTool, LinkerProvider):
  options_scope = 'llvm'
  default_version = '6.0.0'
  archive_type = 'tgz'

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  def linker(self, platform):
    return Linker(
      path_entries=self.path_entries(),

    )
