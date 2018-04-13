# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.binaries.binary_tool import ExecutablePathProvider, NativeTool
from pants.util.contextutil import pushd
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from pants.util.process_handler import subprocess


class Clang(NativeTool, ExecutablePathProvider):
  options_scope = 'clang'
  default_version = '6.0.0'
  archive_type = 'tgz'

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  @memoized_property
  def _cpp_compiler_path(self):
    return os.path.join(self.select(), 'bin', 'clang++')

  @memoized_property
  def _cpp_linker_path(self):
    return os.path.join(self.select(), 'bin', 'ld64.lld')

  def _copy_sources(self, outdir, src_dir, src_rel_paths):
    for src_rel in src_rel_paths:
      output_rel = os.path.join(outdir, src_rel)
      safe_mkdir(os.path.dirname(output_rel))
      abs_src_path = os.path.join(src_dir, src_rel)
      shutil.copyfile(abs_src_path, output_rel)

  @contextmanager
  def compile_environment(self, outdir, src_dir, src_rel_paths):
    self._copy_sources(outdir, src_dir, src_rel_paths)

    with pushd(outdir):
      yield

  def compile_cpp(self, outdir, src_dir, src_rel_paths):
    with self.compile_environment(outdir, src_dir, src_rel_paths):
      argv = [self._cpp_compiler_path, '-c'] + src_rel_paths
      return subprocess.check_output(argv=argv, cwd=outdir)

  def _copy_objects(self, outdir, obj_dir, obj_rel_paths):
    for obj_rel in obj_rel_paths:
      output_rel = os.path.join(outdir, obj_rel)
      safe_mkdir(os.path.dirname(output_rel))
      abs_obj_path = os.path.join(obj_dir, obj_rel)
      shutil.copyfile(abs_obj_path, output_rel)

  @contextmanager
  def link_environment(self, outdir, obj_dir, obj_rel_paths):
    self._copy_objects(outdir, obj_dir, obj_rel_paths)

    with pushd(outdir):
      yield

  def link_cpp(self, outdir, obj_dir, outfile_name, obj_rel_paths):
    with self.link_environment(outdir, obj_dir, obj_rel_paths):
      argv = [self._cpp_linker_path, '-o', outfile_name] + obj_rel_paths
      return subprocess.check_output(argv=argv, cwd=outdir)
