# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_util import BinaryUtil
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class PythonNativeToolchain(object):
  """Represents a self-boostrapping set of binaries and libraries used to
  compile native code in for python dists."""

  class Factory(Subsystem):
    options_scope = 'python-native-toolchain'

    @classmethod
    def subsystem_dependencies(cls):
      return (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      register('--supportdir', advanced=True,
               help='Find the go distributions under this dir.  Used as part '
                    'of the path to lookup the distribution with '
                    '--binary-util-baseurls and --pants-bootstrapdir',
               default='bin/python-native-toolchain')
      register('--clang-version', advanced=True,
               help='Clang version used to compile python native extensions.  '
                    'Used as part of the path to lookup the distribution '
                    'with --binary-util-baseurls and --pants-bootstrapdir',
               default='5.0.0')

    # NB: create() is an instance method to allow the user to choose global or
    # scoped -- It's not unreasonable to imagine different stacks for different
    # python versions. Get an instance of this with
    # PythonNativeToolchain.Factory.scoped_instance(self).create()!
    def create(self):
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      return PythonNativeToolchain(binary_util=binary_util,
                                   relpath=options.supportdir,
                                   clang_version=options.clang_version)

  def __init__(self, binary_util, relpath, clang_version):
    self._binary_util = binary_util
    self._relpath = relpath
    self._clang_version = clang_version

  @property
  def clang_version(self):
    return self._clang_version

  @memoized_property
  def clang_path(self):
    return self._binary_util.select_binary(
      self._relpath, self.clang_version, 'clang')
