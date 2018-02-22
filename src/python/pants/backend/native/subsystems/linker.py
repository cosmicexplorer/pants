# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_tool import NativeTool


class Linker(NativeTool):
  options_scope = 'linker'
  default_version = '2.30-e527b6f8'
  archive_type = 'tgz'
