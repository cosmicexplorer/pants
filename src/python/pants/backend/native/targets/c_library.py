# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

from pants.backend.native.targets.native_library import NativeLibrary


class CLibrary(NativeLibrary):
  """???"""

  default_sources_globs = [
    '*.h',
    '*.c',
  ]

  @classmethod
  def alias(cls):
    return 'ctypes_compatible_c_library'
