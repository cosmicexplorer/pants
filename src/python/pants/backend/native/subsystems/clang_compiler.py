# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.native.subsystems.toolchain_component import ToolchainComponent
from pants.backend.native.subsystems.binaries.clang import Clang


class ClangCompiler(ToolchainComponent):

  @classmethod
  def subsystem_dependencies(cls):
    return super(ClangCompiler, cls).subsystem_dependencies() + (Clang.scoped(cls),)

  def invocation(source_files):
