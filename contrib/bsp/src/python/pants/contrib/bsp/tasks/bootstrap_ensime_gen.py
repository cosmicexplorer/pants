# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.util.memo import memoized_property

from pants.contrib.bsp.subsystems.ensime_gen_source import EnsimeGenSource
from pants.contrib.bsp.tasks.bootstrap_jvm_source_tool import BootstrapJvmSourceTool


class BootstrapEnsimeGen(BootstrapJvmSourceTool):

  workunit_component_name = 'ensime-gen'

  @classmethod
  def subsystem_dependencies(cls):
    return super(BootstrapEnsimeGen, cls).subsystem_dependencies() + (EnsimeGenSource.scoped(cls),)

  @memoized_property
  def _ensime_gen_source(self):
    return EnsimeGenSource.scoped_instance(self)

  @memoized_property
  def binary_tool_target(self):
    return self._ensime_gen_source.ensime_gen_binary
