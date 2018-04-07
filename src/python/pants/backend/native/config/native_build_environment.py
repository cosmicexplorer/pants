# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.util.objects import datatype
from pants.util.process_handler import subprocess


class NativeBuildConfigurationError(Exception): pass


def _invoke_capturing_output(cmd):
  try:
    return subprocess.check_output(cmd)
  except subprocess.CalledProcessError as e:
    raise NativeBuildConfigurationError(
      "Command '{cmd}' failed with code '{code}'. "
      "Combined stdout and stderr:\n{out}"
      .format(cmd=' '.join(cmd), code=e.returncode, out=e.output),
      e)


class NativeBuildEnvironment(datatype('NativeBuildEnvironment', [
    'program_dirs',
    'lib_dirs',
    'include_dirs',
])):

  @classmethod
  def _normalize_dir_set(cls, dir_set, name):
    real_dir_paths = set()

    for entry in dir_set:
      if not os.path.isdir(entry):
        raise TypeError("'{}' in {} is not an existing directory!"
                        .format(repr(entry), name))
      real_dir = os.path.realpath(entry)
      real_dir_paths.add(real_dir)

    return real_dir_paths

  def __new__(cls, program_dirs, lib_dirs, include_dirs):
    return super(NativeBuildEnvironment, cls).__new__(
      cls,
      cls._normalize_dir_set(program_dirs, 'program_dirs'),
      cls._normalize_dir_set(lib_dirs, 'lib_dirs'),
      cls._normalize_dir_set(include_dirs, 'include_dirs'),
    )

  @classmethod
  def create_from_compiler_invocation(cls, compiler_exe):
    search_dirs_cmd = [compiler_exe, '-print-search-dirs']
    search_dirs_output = _invoke_capturing_output(search_dirs_cmd)

    program_dirs = set()
    lib_dirs = set()
    include_dirs = set()

    for out_line in search_dirs_output.splitlines():
      programs_match = re.match(r'^programs: =(.*$)', out_line)
      if programs_match:
        program_dir_paths = programs_match.group(1).split(':')
        program_dirs.update(program_dir_paths)
        continue

      libraries_match = re.match(r'^libraries: =(.*$)', out_line)
      if libraries_match:
        lib_dir_paths = libraries_match.group(1).split(':')
        lib_dirs.update(lib_dir_paths)

        for lib_dir in lib_dir_paths:
          potential_include_dir = os.path.join(lib_dir, 'include')
          if os.path.isdir(potential_include_dir):
            include_dirs.add(potential_include_dir)

        continue

    return cls(program_dirs, lib_dirs, include_dirs)

  @classmethod
  def empty(cls):
    return cls(
      program_dirs=set(),
      lib_dirs=set(),
      include_dirs=set(),
    )

  def compose(self, rhs):
    # NB: runs all the validation in __new__ again
    return NativeBuildEnvironment(
      self.program_dirs | rhs.program_dirs,
      self.lib_dirs | rhs.lib_dirs,
      self.include_dirs | rhs.include_dirs,
    )

  @classmethod
  def compose_all(cls, envs):
    cur = cls.empty()

    for build_env in envs:
      cur = cur.compose(build_env)

    return cur
