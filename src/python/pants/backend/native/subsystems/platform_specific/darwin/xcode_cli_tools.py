# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.native_build_environment import NativeBuildEnvironment
from pants.backend.native.config.native_toolchain_component_mixin import NativeToolchainComponentMixin
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_executable


# FIXME(cosmicexplorer): remove this and provide lld to replace it: see #5663
class XCodeCLITools(Subsystem, NativeToolchainComponentMixin):
  """Subsystem to detect and provide the XCode command line developer tools.

  This subsystem exists to give a useful error message if the tools aren't
  installed, and because the install location may not be on the PATH when Pants
  is invoked."""

  options_scope = 'xcode-cli-tools'

  _INSTALL_LOCATION = '/usr/bin'

  _REQUIRED_TOOLS = frozenset(['clang', 'clang++', 'ld', 'lipo'])

  class XCodeToolsUnavailable(Exception):
    """Thrown if the XCode CLI tools could not be located."""

  def _check_executables_exist(self):
    for filename in self._REQUIRED_TOOLS:
      executable_path = os.path.join(self._INSTALL_LOCATION, filename)
      if not is_executable(executable_path):
        raise self.XCodeToolsUnavailable(
          "'{}' is not an executable file, but it is required to build "
          "native code on this platform. You may need to install the XCode "
          "command line developer tools."
          .format(executable_path))

  def get_config(self):
    xcode_clang_exe = os.path.join(self._INSTALL_LOCATION, 'clang')
    return NativeBuildEnvironment.create_from_compiler_invocation(xcode_clang_exe)
