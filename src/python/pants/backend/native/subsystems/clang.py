# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_tool import NativeTool
from pants.util.memo import memoized_property
from pants.util.process_handler import subprocess


class Clang(NativeTool):
  options_scope = 'clang'
  default_version = '5.0.1'
  archive_type = 'tgz'

  @memoized_property
  def exe_path(self):
    return os.path.join(self.select(), 'bin', 'clang')

  def _call_subproc(self, workunit, cmd):
    try:
      subprocess.check_call(cmd,
                            stdout=workunit.output('stdout'),
                            stderr=workunit.output('stderr'))
    except subprocess.CalledProcessError as e:
      raise TaskError('{} ... exited non-zero ({}).'.format(' '.join(cmd), e.returncode))

  def compile_to_objects(self, workunit, source_files, include_dirs, language):
    cmd = [self.exe_path, '-x', language, '-fPIC']
    for src_file in source_files:
      cmd.extend(['-c', src_file])
    for inc_dir in include_dirs:
      cmd.append('-I{}'.format(inc_dir))
    self._call_subproc(workunit, cmd)
