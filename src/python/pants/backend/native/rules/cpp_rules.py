# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from hashlib import sha1

from abc import abstractmethod

from pants.backend.native.subsystems.clang import Clang
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.rules import RootRule, SingletonRule, rule
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
                            .format(rel_path, root_dir))

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

  def __hash__(self):
    hasher = sha1()
    hasher.update(self.root_dir)
    for p in self.file_paths:
      hasher.update(p)

    return hash(hasher.digest())

  def as_cpp_files(self):
    return CppFiles(self.root_dir, self.file_paths)


class CppSourceSnapshot(datatype('CppSourceSnapshot', [
    'relative_to',
    'snapshot',
])):

  def get_relative_file_paths(self):
    rel_paths = []

    abs_paths = [f.stat.path for f in self.snapshot.files]

    for p in abs_paths:
      relative_to_orig_root = os.path.relpath(p, start=self.relative_to)
      rel_paths.append(relative_to_orig_root)

    return rel_paths


@rule(CppSourceSnapshot, [Select(CppSources)])
def collect_cpp_sources(cpp_sources):
  snapshot = yield Get(Snapshot, PathGlobs, cpp_sources.as_path_globs())
  yield CppSourceSnapshot(relative_to=cpp_sources.root_dir, snapshot=snapshot)


# TODO: validate that these are actually compiled cpp object files (how?)
class CppObjects(datatype('CppObjects', [
    'root_dir',
    'file_paths',
])):

  def __hash__(self):
    hasher = sha1()
    hasher.update(self.root_dir)
    for p in self.file_paths:
      hasher.update(p)

    return hash(hasher.digest())

  def as_cpp_files(self):
    return CppFiles(self.root_dir, self.file_paths)


class CppObjectsRequest(datatype('CppObjectsRequest', [
    'sources',
    'dir_path',
])): pass


@rule(CppObjects, [Select(Clang), Select(CppObjectsRequest)])
def compile_cpp_sources_to_objects(compiler, cpp_objects_request):
  src_snapshot = yield Get(CppSourceSnapshot, CppSources, cpp_objects_request.sources)
  src_rel_paths = src_snapshot.get_relative_file_paths()

  outdir = cpp_objects_request.dir_path

  expected_object_file_paths = [
    re.sub(r'\.cpp\Z', '.o', cpp_src) for cpp_src in src_rel_paths
  ]

  compiler.compile_cpp(outdir, src_snapshot.relative_to, src_rel_paths)

  yield CppObjects(outdir, expected_object_file_paths)


class CppObjectSnapshot(datatype('CppObjectSnapshot', [
    'relative_to',
    'snapshot',
])):

  def get_relative_file_paths(self):
    rel_paths = []

    abs_paths = [f.stat.path for f in self.snapshot.files]

    for p in abs_paths:
      relative_to_orig_root = os.path.relpath(p, start=self.relative_to)
      rel_paths.append(relative_to_orig_root)

    return rel_paths


@rule(CppObjectSnapshot, [Select(CppObjects)])
def collect_cpp_objects(cpp_objects):
  snapshot = yield Get(Snapshot, PathGlobs, cpp_objects.as_path_globs())
  yield CppObjectSnapshot(relative_to=cpp_objects.root_dir, snapshot=snapshot)


class CppDylib(datatype('CppDylib', [
    'relative_to',
    'rel_path',
])):

  def as_path_globs(self):
    return PathGlobs.create(relative_to=self.relative_to,
                            include=[self.rel_path])


class CppDylibSnapshot(datatype('CppDylibSnapshot', [
    'snapshot',
])): pass


@rule(CppDylibSnapshot, [Select(CppDylib)])
def collect_cpp_dylib(cpp_dylib):
  snapshot = yield Get(Snapshot, PathGlobs, cpp_dylib.as_path_globs())
  yield CppDylibSnapshot(snapshot=snapshot)


class CppDylibRequest(datatype('CppDylibRequest', [
    'cpp_objects',
    'output_filename',
    'dir_path',
])): pass


# @rule(CppDylib, [Select(Linker), Select(CppDylibRequest)])
# def link_objects_into_dylib(linker, cpp_dylib_request):
#   obj_snapshot = yield Get(CppObjectSnapshot, CppObjects, cpp_dylib_request.cpp_objects)

#   obj_rel_paths = obj_snapshot.get_relative_file_paths()

#   outdir = cpp_dylib_output_dir.dir_path

#   output_filename = cpp_link_request.output_filename

#   linker.link_cpp(outdir, obj_snapshot.relative_to, output_filename, obj_rel_paths)

#   yield CppDylib(relative_to=outdir, rel_path=output_filename)


def create_cpp_rules(clang_inst):
  return [
    SingletonRule(Clang, clang_inst),
    RootRule(CppObjectsRequest),
    # SingletonRule(Linker, linker_inst),
    RootRule(CppDylibRequest),
    collect_cpp_sources,
    collect_cpp_objects,
    compile_cpp_sources_to_objects,
    # collect_cpp_dylib,
    # link_objects_into_dylib,
  ]
