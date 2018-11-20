# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task
from pants.contrib.bsp.subsystems.sbt import Sbt
from pants.contrib.bsp.targets.custom_scala_dependencies import \
    CustomScalaDependencies
from pants.contrib.bsp.targets.custom_scrooge_dependencies import \
    CustomScroogeDependencies
from pants.contrib.bsp.targets.custom_scrooge_java_thrift_library import \
    CustomScroogeJavaThriftLibrary
from pants.contrib.bsp.targets.pants_jvm_binary_subproject import PantsJvmBinarySubproject
from pants.contrib.bsp.targets.sbt_dist import SbtDist
from pants.contrib.bsp.tasks.bootstrap_coursier import BootstrapCoursier
from pants.contrib.bsp.tasks.bootstrap_bsp_gen import BootstrapBspGen
from pants.contrib.bsp.tasks.custom_scrooge import CustomScrooge
from pants.contrib.bsp.tasks.bsp_gen import BspGen
from pants.contrib.bsp.tasks.publish_local_sbt_distributions import \
    PublishLocalSbtDistributions


def build_file_aliases():
  return BuildFileAliases(
    targets={
      CustomScroogeJavaThriftLibrary.alias(): CustomScroogeJavaThriftLibrary,
      PantsJvmBinarySubproject.alias(): PantsJvmBinarySubproject,
      SbtDist.alias(): SbtDist,
    },
    context_aware_object_factories={
      CustomScalaDependencies.alias(): CustomScalaDependencies,
      CustomScroogeDependencies.alias(): CustomScroogeDependencies,
    },
  )


def global_subsystems():
  return {Sbt}


def register_goals():
  task(
    name='publish-local-sbt-distributions',
    action=PublishLocalSbtDistributions
  ).install('bootstrap')
  task(
    name='bootstrap-coursier',
    action=BootstrapCoursier,
  ).install('bootstrap')
  task(
    name='bootstrap-bsp-gen',
    action=BootstrapBspGen,
  ).install('bootstrap')
  task(name='custom-scrooge', action=CustomScrooge).install('gen')
  task(name='bsp-gen', action=BspGen).install('bsp')
