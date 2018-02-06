# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pex.executor import Executor
from pex.interpreter import PythonInterpreter

from pants.binaries.binary_util import BinaryUtil
from pants.fs.archive import TGZ
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir, environment_as
from pants.util.memo import memoized_method


INC_DIR_INPUT = b"""
import sys
from distutils import sysconfig

sys.stdout.write(sysconfig.get_python_inc())
"""


class SandboxedInterpreter(PythonInterpreter):

  class ToolchainLocationError(Exception):
    def __init__(self, dir_path):
      msg = "path '{}' does not exist or is not a directory".format(dir_path)
      super(ToolchainLocationError, self).__init__(msg)

  class BaseInterpreterError(Exception): pass

  def __init__(self, llvm_toolchain_dir, base_interp):

    if not os.path.isdir(llvm_toolchain_dir):
      raise ToolchainLocationError(llvm_toolchain_dir)
    if not isinstance(base_interp, PythonInterpreter):
      raise BaseInterpreterError("invalid PythonInterpreter: '{}'".format(repr(base_interp)))

    self._llvm_toolchain_dir = llvm_toolchain_dir

    super(SandboxedInterpreter, self).__init__(
      base_interp.binary, base_interp.identity, extras=base_interp.extras)

  # made into an instance method here (unlike parent class) to use
  # self._llvm_toolchain_dir
  @memoized_method
  def sanitized_environment(self):
    pre_sanitized_env = super(SandboxedInterpreter, self).sanitized_environment()
    pre_sanitized_env['PATH'] = os.path.join(self._llvm_toolchain_dir, 'bin')

    llvm_include = os.path.join(self._llvm_toolchain_dir, 'include')
    python_inc_stdout, _ = Executor.execute([self.binary], env=pre_sanitized_env, stdin_payload=INC_DIR_INPUT)
    pre_sanitized_env['CPATH'] = '{}:{}'.format(llvm_include, python_inc_stdout)

    # TODO: we may not need this. if removed, (probably) remove the 'lib/' dir
    # from the llvm packaging script too!
    # pre_sanitized_env['LD_LIBRARY_PATH'] = os.path.join(self._llvm_toolchain_dir, 'lib')
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
      register('--llvm-version', advanced=True,
               help='LLVM version used to compile python native extensions.  '
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
                                   llvm_version=options.llvm_version)

  def __init__(self, binary_util, relpath, llvm_version):
    self._binary_util = binary_util
    self._relpath = relpath
    self._llvm_version = llvm_version

  @memoized_method
  def llvm_toolchain_dir(self):
    llvm_archive_path = self._binary_util.select_binary(
      self._relpath, self._llvm_version, 'llvm-tools.tar.gz')
    distribution_workdir = os.path.dirname(llvm_archive_path)
    outdir = os.path.join(distribution_workdir, 'unpacked')
    if not os.path.exists(outdir):
      with temporary_dir(root_dir=distribution_workdir) as tmp_dist:
        TGZ.extract(llvm_archive_path, tmp_dist)
        os.rename(tmp_dist, outdir)
    return outdir
