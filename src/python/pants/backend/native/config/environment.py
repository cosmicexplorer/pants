# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from abc import abstractmethod, abstractproperty

from pants.util.contextutil import environment_as, get_joined_path
from pants.util.objects import datatype


class Platform(datatype('Platform', ['normed_os_name'])):
  pass


class Executable(object):

  @abstractproperty
  def path_entries(self):
    """???"""

  @abstractproperty
  def exe_filename(self):
    """???"""


class Linker(datatype('Linker', [
    'path_entries',
    'exe_filename',
]), Executable):
  pass


class LinkerProvider(object):

  @abstractmethod
  def linker(self, platform): pass


class Compiler(datatype('Compiler', [
    'path_entries',
    'exe_filename',
    ''
]), Executable):
  pass


class BootstrapEnvironment(datatype('BootstrapEnvironment', [
    'cc',
    'cxx',
    'c_include_path',
    'cplus_include_path',
    'ld',
    'library_path',
    'exec_path',
])):
  """Contains the components of the native toolchain which Pants must provide.
  This does not wrap up any source files, 3rdparty library locations, or
  anything else that the user provides."""

  @contextmanager
  def native_toolchain_invocation(self):
    sealed_native_toolchain_path = get_joined_path(self.exec_path)
