# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from abc import abstractmethod, abstractproperty

from pants.engine.rules import SingletonRule, rule
from pants.util.objects import datatype
from pants.util.osutil import all_normalized_os_names, get_normalized_os_name


class UnsupportedPlatformError(Exception):
  """Thrown if the native toolchain is invoked on an unrecognized platform.

    Note that the native toolchain should work on all of Pants's supported
    platforms."""


class Platform(datatype('Platform', ['normed_os_name'])):

  @classmethod
  def create(cls):
    return Platform(get_normalized_os_name())

  _NORMED_OS_NAMES = frozenset(all_normalized_os_names())

  def resolve_platform_specific(self, platform_dict):
    arg_keys = frozenset(platform_dict.keys())
    unknown_plats = self._NORMED_OS_NAMES - arg_keys
    if unknown_plats:
      raise UnsupportedPlatformError(
        "platform_dict {!r} must support platforms {!r}"
        .format(platform_dict, list(unknown_plats)))
    extra_plats = arg_keys - self._NORMED_OS_NAMES
    if extra_plats:
      raise UnsupportedPlatformError(
        "platform_dict {!r} has unrecognized platforms {!r}"
        .format(platform_dict, list(extra_plats)))

    return platform_dict[self.normed_os_name]


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


class CCompiler(datatype('CCompiler', [
    'path_entries',
    'exe_filename',
]), Executable):
  pass


class CppCompiler(datatype('Compiler', [
    'path_entries',
    'exe_filename',
]), Executable):
  pass


def create_native_environment_rules():
  return [
    SingletonRule(Platform, Platform.create()),
  ]
