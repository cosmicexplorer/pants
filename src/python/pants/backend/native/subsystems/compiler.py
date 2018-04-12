# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import shutil
from contextlib import contextmanager

from abc import abstractmethod

from pants.util.contextutil import pushd
from pants.util.dirutil import safe_mkdir


class Compiler(object):
  @abstractmethod
  def compile_cpp(self, outdir, src_file_paths): pass

  def _copy_sources(self, outdir, src_file_paths):
    for src_rel in src_file_paths:
      output_rel = os.path.join(outdir, src_rel)
      safe_mkdir(os.path.dirname(output_rel))
      abs_src_path = os.path.join(get_buildroot(), src_rel)
      shutil.copyfile(abs_src_path, output_rel)

  @contextmanager
  def compile_environment(self, outdir, src_file_paths):
    self._copy_sources(outdir, src_file_paths)

    with pushd(outdir):
      yield
