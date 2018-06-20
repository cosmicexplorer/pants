# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

from pants.engine.rules import SingletonRule
from pants.util.objects import datatype
from pants.util.osutil import all_normalized_os_names, get_normalized_os_name


class UnsupportedPlatformError(Exception):
  """Thrown if the native toolchain is invoked on an unrecognized platform.

    Note that the native toolchain should work on all of Pants's supported
    platforms."""


class Platform(datatype(['normalized_os_name'])):

  @classmethod
  def create(cls):
    return Platform(get_normalized_os_name())

  _NORMALIZED_OS_NAMES = frozenset(all_normalized_os_names())

  def resolve_platform_specific(self, platform_specific_funs):
    arg_keys = frozenset(platform_specific_funs.keys())
    unknown_plats = self._NORMED_OS_NAMES - arg_keys
    if unknown_plats:
      raise UnsupportedPlatformError(
        "platform_specific_funs {} must support platforms {}"
        .format(platform_specific_funs, list(unknown_plats)))
    extra_plats = arg_keys - self._NORMED_OS_NAMES
    if extra_plats:
      raise UnsupportedPlatformError(
        "platform_specific_funs {} has unrecognized platforms {}"
        .format(platform_specific_funs, list(extra_plats)))

    fun_for_platform = platform_specific_funs[self.normalized_os_name]
    return fun_for_platform()


class Executable(object):

  @abstractproperty
  def path_entries(self):
    """???"""

  @abstractproperty
  def exe_filename(self):
    """???"""


class Linker(datatype([
    'path_entries',
    'exe_filename',
]), Executable):
  pass


class CCompiler(datatype([
    'path_entries',
    'exe_filename',
]), Executable):
  pass


class CppCompiler(datatype([
    'path_entries',
    'exe_filename',
]), Executable):
  pass


def create_native_environment_rules():
  return [
    SingletonRule(Platform, Platform.create()),
  ]
