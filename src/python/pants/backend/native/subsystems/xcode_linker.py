# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.clang import Clang
from pants.binaries.host_installed_tool_base import HostInstalledToolBase
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.memo import memoized_property
from pants.util.process_handler import subprocess


HELLO_WORLD_C_SOURCE = '''
#include <stdio.h>

int main() {
    printf("%s\n", "Hello, world!");
}
'''


class XCodeLinker(HostInstalledToolchainBase):
  options_scope = 'xcode-linker'
  name = 'ld'
  default_tool_path = '/usr/bin/ld'
  complete_install_instructions = '''Run the following command in a terminal:

xcode-select --install

Click "Install" in the dialog box that pops up, and wait for installation to
complete.
'''

  @classmethod
  def subsystem_dependencies(cls):
    return super(XCodeLinker, cls).subsystem_dependencies() + (Clang.scoped(cls))

  @memoized_property
  def _clang(self):
    return Clang.scoped_instance(self)

  def validate_host_tool(self, host_path):
    ld_host_binary = super(XCodeLinker, self).validate_host_tool(
      host_path, context)

    with temporary_dir() as tmpdir:
      c_source = os.path.join(tmpdir, 'hello.c')
      with open(c_source, 'w') as fp:
        fp.write(HELLO_WORLD_C_SOURCE)

      ld_bin_dir = os.path.dirname(ld_host_binary)
      scrubbed_path = '{}:{}'.format(self._clang.bin_dir(), ld_bin_dir)
      with environment_as(PATH=scrubbed_path):
        subprocess.call(['clang', 'hello.c', '-o', 'hello'],
                        cwd=tmpdir)
        hello_stdout = subprocess.check_output(['./hello'], cwd=tmpdir)
        if hello_stdout != 'Hello, World!\n':
          raise Exception("BAD STDOUT: '{}'".format(hello_stdout))

    return ld_host_binary
