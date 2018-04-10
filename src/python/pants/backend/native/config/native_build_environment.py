# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re

from abc import abstractmethod
from twitter.common.collections import OrderedSet

from pants.util.memo import memoized_property
from pants.util.objects import datatype
from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


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


class DirectoryPathEntries(datatype('DirectoryPathEntries', ['name', 'dirs'])):

  @classmethod
  def _check_name(cls, name):
    if not isinstance(name, str):
      raise TypeError("'name' argument must be a string! was: {}"
                      .format(repr(name)))

    if len(name) == 0:
      raise TypeError("'name' argument must be non-empty!".format(name))

    return name

  @classmethod
  def _normalize_dir_set(cls, dir_paths, checked_name):
    real_dir_paths = OrderedSet()

    if not dir_set:
      return real_dir_paths

    for entry in dir_paths:
      if not os.path.isdir(entry):
        logger.debug("nonexistent directory '{}' deselected for {}"
                     .format(entry, checked_name))
        continue
      real_dir = os.path.realpath(entry)
      real_dir_paths.add(real_dir)

    return real_dir_paths

  @classmethod
  def create(cls, name, iterable=None):
    checked_name = cls._check_name(name)
    return cls(
      name=checked_name,
      dirs=cls._normalize_dir_set(iterable, checked_name),
    )


# TODO(cosmicexplorer): fingerprint the bootstrap options?
class NativeBuildBootstrapEnvironment(datatype('NativeBuildBootstrapEnvironment', [
    'program_dirs',
    'lib_dirs',
    'include_dirs',
])):

  @classmethod
  def create(cls, program_dirs=None, lib_dirs=None, include_dirs=None):
    return cls(
      program_dirs=DirectoryPathEntries.create('program_dirs', program_dirs),
      lib_dirs=DirectoryPathEntries.create('lib_dirs', lib_dirs),
      include_dirs=DirectoryPathEntries.create('include_dirs', include_dirs),
    )

  def __new__(cls, program_dirs, lib_dirs, include_dirs):
    return super(NativeBuildBootstrapEnvironment, cls).__new__(
      cls,
      program_dirs=OrderedSet(program_dirs),
      lib_dirs=OrderedSet(lib_dirs),
      include_dirs=OrderedSet(include_dirs),
    )

  @classmethod
  def create_from_compiler_invocation(cls, compiler_exe):
    search_dirs_cmd = [compiler_exe, '-print-search-dirs']
    search_dirs_output = _invoke_capturing_output(search_dirs_cmd)

    program_dirs = OrderedSet()
    lib_dirs = OrderedSet()
    include_dirs = OrderedSet()

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

    return cls.create(program_dirs, lib_dirs, include_dirs)

  @classmethod
  def empty(cls):
    return cls(
      program_dirs=set(),
      lib_dirs=set(),
      include_dirs=set(),
    )

  def compose(self, rhs):
    # NB: runs all the validation in __new__ again
    return NativeBuildBootstrapEnvironment(
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


class NativeCompilerMixin(object):

  @abstractmethod
  def invoke(self, )

  @memoized_property
  def config(self):
    return self.get_config()

  @abstractmethod
  def get_config(self): pass
