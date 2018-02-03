# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pex.interpreter import PythonInterpreter

from pants.binaries.binary_util import BinaryUtil
from pants.fs.archive import TGZ
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir, environment_as
from pants.util.memo import memoized_method


class SandboxedInterpreter(PythonInterpreter):
  """???"""

  class BinaryDirectoryError(Exception):
    def __init__(self, dir_path):
      msg = "path '{}' does not exist or is not a directory".format(dir_path)
      super(BinaryDirectoryError, self).__init__(msg)

  class BaseInterpreterError(Exception): pass

  def __init__(self, clang_bin_dir_path, base_interp):

    if not os.path.isdir(clang_bin_dir_path):
      raise BinaryDirectoryError(clang_bin_dir_path)
    if not isinstance(base_interp, PythonInterpreter):
      raise BaseInterpreterError("invalid PythonInterpreter: '{}'".format(repr(base_interp)))

    self._clang_bin_dir_path = clang_bin_dir_path

    super(SandboxedInterpreter, self).__init__(
      base_interp.binary, base_interp.identity, extras=base_interp.extras)

  # made into an instance method here to use self._clang_bin_dir_path
  def sanitized_environment(self):
    pre_sanitized_env = super(SandboxedInterpreter, self).sanitized_environment()
    pre_sanitized_env['PATH'] = self._clang_bin_dir_path
    # TODO: see Lib/distutils/sysconfig.py and Lib/_osx_support.py in CPython.
    # this line tells distutils to only compile for 64-bit archs -- if not, it
    # will attempt to build a fat binary for 32- and 64-bit archs, which makes
    # clang invoke "lipo", an osx command which does not appear to be open
    # source.
    pre_sanitized_env['ARCHFLAGS'] = '-arch x86_64'
    for env_var in ['CC', 'CXX']:
      pre_sanitized_env.pop(env_var, None)
    return pre_sanitized_env


class PythonNativeToolchain(object):
  """Represents a self-boostrapping set of binaries and libraries used to
  compile native code in for python dists."""

  class InvalidToolRequest(Exception):

    def __init__(self, rel_path_requested):
      msg = "relative path '{}' does not exist in the python native toolchain".format(rel_path_requested)
      super(InvalidToolRequest, self).__init__(msg)

  class Factory(Subsystem):
    options_scope = 'python-native-toolchain'

    @classmethod
    def subsystem_dependencies(cls):
      return super(PythonNativeToolchain.Factory, cls).subsystem_dependencies() + (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      super(PythonNativeToolchain.Factory, cls).register_options(register)
      register('--supportdir', advanced=True,
               help='Find the go distributions under this dir.  Used as part '
                    'of the path to lookup the distribution with '
                    '--binary-util-baseurls and --pants-bootstrapdir',
               default='bin/python-native-toolchain')
      register('--clang-version', advanced=True,
               help='Clang version used to compile python native extensions.  '
                    'Used as part of the path to lookup the distribution '
                    'with --binary-util-baseurls and --pants-bootstrapdir',
               default='5.0.1')

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

  @memoized_method
  def _clang_llvm_distribution_base(self):
    clang_archive_path = self._binary_util.select_binary(
      self._relpath, self._clang_version, 'clang+llvm.tar.gz')
    distribution_workdir = os.path.dirname(clang_archive_path)
    outdir = os.path.join(distribution_workdir, 'unpacked')
    if not os.path.exists(outdir):
      with temporary_dir(root_dir=distribution_workdir) as tmp_dist:
        TGZ.extract(clang_archive_path, tmp_dist)
        os.rename(tmp_dist, outdir)
    return outdir

  @memoized_method
  def clang_bin_dir_path(self):
    dist_base = self._clang_llvm_distribution_base()
    bin_dir_path = os.path.join(dist_base, 'bin')
    if not os.path.exists(bin_dir_path):
      raise InvalidToolRequest('bin')
    return bin_dir_path
