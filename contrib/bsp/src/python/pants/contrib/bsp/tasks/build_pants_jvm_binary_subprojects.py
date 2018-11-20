# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.task.task import Task
from pants.util.objects import datatype
from pants.contrib.bsp.tasks.bootstrap_jvm_source_tool import BootstrapJar


class BuildPantsJvmBinarySubprojects(Task): pass
