# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from abc import abstractmethod

from pants.backend.native.subsystems.compiler import Compiler
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Select
from pants.util.objects import datatype


class CppFilesError(Exception): pass


class CppFiles(datatype('CppFiles', [
    'root_dir',
    'file_paths',
])):

  def __new__(cls, root_dir, file_paths):
    if not os.path.isdir(root_dir):
      raise CppFilesError("root dir '{}' does not exist!"
                          .format(root_dir))

    for rel_path in file_paths:
      abs_path = os.path.join(root_dir, rel_path)
      if not os.path.isfile(abs_path):
        raise CppFilesError("rel path '{}' is not a file (from cwd '{}')"
                            .format(root_dir, rel_path))

    return super(CppFiles, cls).__new__(cls, root_dir, file_paths)

class CppFileProvider(object):

  @abstractmethod
  def as_cpp_files(self): pass

  def as_path_globs(self):
    cpp_files = self.as_cpp_files()
    return PathGlobs.create(cpp_files.root_dir, include=cpp_files.file_paths)


# TODO: ensure the input files are valid cpp sources files (how?)
class CppSources(datatype('CppSources', [
    'root_dir',
    'file_paths',
]), CppFileProvider):

  def as_cpp_files(self):
    return CppFiles(self.root_dir, self.file_paths)


# TODO: validate that these are actually compiled cpp object files (how?)
class CppObjects(datatype('CppObjects', [
    'root_dir',
    'file_paths',
])):

  def as_cpp_files(self):
    return CppFiles(self.root_dir, self.file_paths)

class CppOutputDir(datatype('CppOutputDir', [
    'dir_path',
])): pass


@rule(CppObjects, [Select(Compiler), Select(CppSources), Select(CppOutputDir)])
def compile_cpp_sources_to_objects(compiler, cpp_sources, cpp_output_dir):
  src_globs = _sources_to_globs(cpp_sources.root_dir, cpp_sources.file_paths)
  src_snapshot = yield Get(Snapshot, PathGlobs, src_globs)
  src_file_paths = set(f.stat.path for f in src_snapshot.files)

  outdir = cpp_output_dir.dir_path

  expected_object_file_paths = [
    re.sub(r'\.cpp\Z', '.o', cpp_src) for cpp_src in src_file_paths
  ]

  compiler.compile_cpp(outdir, src_file_paths)

  yield CppObjects(outdir, expected_object_file_paths)


def create_cpp_rules():
  return [
    RootRule(Compiler),
    RootRule(CppSources),
    RootRule(CppOutputDir),
    compile_cpp_sources_to_objects,
  ]
