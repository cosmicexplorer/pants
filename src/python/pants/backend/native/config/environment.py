# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.objects import datatype


class BootstrapEnvironment(datatype('BootstrapEnvironment', [
    'cc',
    'cxx',
    'cpath',
    'c_include_path',
    'cplus_include_path',
    'ld',
    'library_path',
    'path',
])):
  """Contains the components of the native toolchain which Pants must provide.
  This does not wrap up any source files, 3rdparty library locations, or
  anything else that the user provides."""
