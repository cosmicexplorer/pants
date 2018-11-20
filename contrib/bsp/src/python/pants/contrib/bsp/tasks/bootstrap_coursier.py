# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.util.memo import memoized_property

from pants.contrib.bsp.subsystems.coursier_source import CoursierSource
from pants.contrib.bsp.tasks.bootstrap_jvm_source_tool import BootstrapJvmSourceTool


class BootstrapCoursier(BootstrapJvmSourceTool):

  workunit_component_name = 'coursier-from-source'

  @classmethod
  def subsystem_dependencies(cls):
    return super(BootstrapCoursier, cls).subsystem_dependencies() + (CoursierSource.scoped(cls),)

  @memoized_property
  def _coursier_source(self):
    return CoursierSource.scoped_instance(self)

  @memoized_property
  def binary_tool_target(self):
    return self._coursier_source.coursier_binary
