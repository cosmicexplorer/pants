# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.util.memo import memoized_property

from pants.contrib.bsp.subsystems.bsp_gen_source import BspGenSource
from pants.contrib.bsp.tasks.bootstrap_jvm_source_tool import BootstrapJvmSourceTool


class BootstrapBspGen(BootstrapJvmSourceTool):

  workunit_component_name = 'bsp-gen'

  @classmethod
  def subsystem_dependencies(cls):
    return super(BootstrapBspGen, cls).subsystem_dependencies() + (BspGenSource.scoped(cls),)

  @memoized_property
  def _bsp_gen_source(self):
    return BspGenSource.scoped_instance(self)

  @memoized_property
  def binary_tool_target(self):
    return self._bsp_gen_source.bsp_gen_binary
