# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.interpreter import PythonInterpreter

from pants.util.memo import memoized_method


class SandboxedInterpreter(PythonInterpreter):

  class ToolchainLocationError(Exception):
    def __init__(self, dir_path):
      msg = "path '{}' does not exist or is not a directory".format(dir_path)
      super(ToolchainLocationError, self).__init__(msg)

  class BaseInterpreterError(Exception): pass

  # using another PythonInterpreter to populate the superclass constructor args
  def __init__(self, llvm_base_dir, base_interp):

    if not os.path.isdir(llvm_base_dir):
      raise ToolchainLocationError(llvm_base_dir)
    if not isinstance(base_interp, PythonInterpreter):
      raise BaseInterpreterError(
        "invalid PythonInterpreter: '{}'".format(repr(base_interp)))

    self._llvm_base_dir = llvm_base_dir

    # this feels a little hacky -- what if pex's PythonInterpreter later needs
    # another constructor arg that's not just a property of the class?
    super(SandboxedInterpreter, self).__init__(
      base_interp.binary, base_interp.identity, extras=base_interp.extras)

  # made into an instance method here (unlike PythonInterpreter superclass) to
  # use instance property self._llvm_base_dir
  @memoized_method
  def sanitized_environment(self):
    sanitized_env = super(SandboxedInterpreter, self).sanitized_environment()

    # use our compiler at the front of the path
    # TODO: when we provide ld and stdlib headers, don't add the original path
    sanitized_env['PATH'] = ':'.join([
      os.path.join(self._llvm_base_dir, 'bin'),
      os.environ.get('PATH'),
    ])

    # TODO: figure out whether we actually should be compiling fat binaries.
    # this line tells distutils to only compile for 64-bit archs -- if not, it
    # will attempt to build a fat binary for 32- and 64-bit archs, which makes
    # clang invoke "lipo", an osx command which does not appear to be open
    # source. see Lib/distutils/sysconfig.py and Lib/_osx_support.py in CPython.
    sanitized_env['ARCHFLAGS'] = '-arch x86_64'

    env_vars_to_scrub = ['CC', 'CXX']
    for env_var in env_vars_to_scrub:
      sanitized_env.pop(env_var, None)

    return sanitized_env
