# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_tool import NativeTool


class Clang(NativeTool):
  options_scope = 'clang'
  default_version = '5.0.1'
  archive_type = 'tgz'

  def bin_dir(self):
    return os.path.join(self.select(), 'bin')
