# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from abc import abstractmethod


class Linker(object):
  @abstractmethod
  def link_cpp(self, outdir, obj_dir, outfile_name, obj_rel_paths): pass

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
