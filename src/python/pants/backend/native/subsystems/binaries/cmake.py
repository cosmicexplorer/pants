# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.binaries.binary_tool import NativeTool
from pants.util.memo import memoized_property


class CMake(NativeTool):
  options_scope = 'cmake'
  default_version = '3.9.5'
  archive_type = 'tgz'

  @memoized_property
  def bin_dir(self):
    return os.path.join(self.select(), 'bin')
