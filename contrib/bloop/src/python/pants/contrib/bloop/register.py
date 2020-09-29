# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.bloop.tasks.compile.bloop_compile import BloopCompile
from pants.contrib.bloop.tasks.compile.bloop_compile import rules as bloop_compile_rules
from pants.contrib.bloop.tasks.config.bloop_export_config import BloopExportConfig
from pants.contrib.bloop.tasks.config.bloop_write_export import BloopWriteExport


def register_goals():
  task(name='bloop-export-config', action=BloopExportConfig).install('bloop-export')
  task(name='bloop-gen', action=BloopWriteExport).install('bloop-export')
  task(name='bloop-compile', action=BloopCompile).install()


def rules():
  return bloop_compile_rules()
