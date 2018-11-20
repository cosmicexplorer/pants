# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.build_environment import get_buildroot, get_pants_cachedir
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.java.util import execute_java
from pants.option.custom_types import target_option
from pants.util.collections import assert_single_element
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_mkdir_for
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf
from pants.contrib.bsp.subsystems.bsp_gen_source import BspGenSource
from pants.contrib.bsp.tasks.bootstrap_jvm_source_tool import BootstrapJar
from pants.contrib.bsp.tasks.modified_export_task_base import ModifiedExportTaskBase


class BspGen(ModifiedExportTaskBase, JvmToolTaskMixin):

  @classmethod
  def register_options(cls, register):
    super(BspGen, cls).register_options(register)

    register('--reported-scala-version', type=str, default=None,
             help='Scala version to report to bsp. Defaults to the scala platform version.')

    register('--scalac-options', type=list,
             default=['-deprecation', '-unchecked', '-Xlint'],
             help='Options to pass to scalac for bsp.')
    register('--javac-options', type=list,
             default=['-deprecation', '-Xlint:all', '-Xlint:-serial', '-Xlint:-path'],
             help='Options to pass to javac for bsp.')
    register('--output-file', type=str, default='.bsp', advanced=True,
             help='Relative path to the buildroot to write the bsp config to.')

  @classmethod
  def prepare(cls, options, round_manager):
    # NB: this is so we run after compile -- we want our class dirs to be populated already.
    round_manager.require_data('runtime_classpath')
    round_manager.require(BootstrapJar)
    cls.prepare_tools(round_manager)

  @classmethod
  def subsystem_dependencies(cls):
    return super(BspGen, cls).subsystem_dependencies() + (
      DistributionLocator,
      ScalaPlatform,
      BspGenSource.scoped(cls),
    )

  @memoized_property
  def _bsp_gen_source(self):
    return BspGenSource.scoped_instance(self)

  def _make_bsp_cache_dir(self):
    bootstrap_dir = get_pants_cachedir()
    cache_dir = os.path.join(bootstrap_dir, 'bsp')
    safe_mkdir(cache_dir)
    return cache_dir

  @memoized_property
  def _scala_platform(self):
    return ScalaPlatform.global_instance()

  @staticmethod
  def _retrieve_single_product_at_target_base(product_mapping, target):
    product = product_mapping.get(target)
    single_base_dir = assert_single_element(product.keys())
    single_product = assert_single_element(product[single_base_dir])
    return single_product

  def execute(self):

    exported_targets_map = self.generate_targets_map(self.context.targets())
    export_result = json.dumps(exported_targets_map, indent=4, separators=(',', ': '))

    with temporary_dir() as tmpdir:
      export_outfile = os.path.join(tmpdir, 'export-out.json')
      with open(export_outfile, 'wb') as outf:
        outf.write(export_result)

      jar_product = self.context.products.get(BootstrapJar)
      bsp_gen_target_address = Address.parse(self._bsp_gen_source.bsp_gen_binary)
      bsp_gen_target = assert_single_element(
        [self.context.build_graph.resolve_address(bsp_gen_target_address)])
      bsp_gen_jar = self._retrieve_single_product_at_target_base(jar_product, bsp_gen_target)
      bsp_gen_classpath = [bsp_gen_jar.tool_jar_path]

      # TODO: use JvmPlatform for jvm options!
      reported_scala_version = self.get_options().reported_scala_version
      if not reported_scala_version:
        reported_scala_version = self._scala_platform.version

      zinc_compile_dir = os.path.join(self.get_options().pants_workdir, 'compile/zinc')

      output_file = os.path.join(get_buildroot(), self.get_options().output_file)
      safe_mkdir_for(output_file)

      # This is what we depend on in 3rdparty/jvm:bsp-server.
      bsp_server_version = '2.0.1'

      bsp_server_jars = self.tool_classpath_from_products(self.context.products, 'bsp-server',
                                                             scope=self.options_scope)

      scala_compiler_jars = self._scala_platform.compiler_classpath(self.context.products)

      argv = [
        get_buildroot(),
        reported_scala_version,
        self._make_bsp_cache_dir(),
        zinc_compile_dir,
        output_file,
        bsp_server_version,
      ]

      env = {
        'SCALAC_ARGS': json.dumps(self.get_options().scalac_options),
        'JAVAC_ARGS': json.dumps(self.get_options().javac_options),
        'ENSIME_SERVER_JARS_CLASSPATH': ':'.join(bsp_server_jars),
        'SCALA_COMPILER_JARS_CLASSPATH': ':'.join(scala_compiler_jars),
      }

      with open(export_outfile, 'rb') as inf:
        with environment_as(**env):
          execute_java(bsp_gen_classpath,
                       'pingpong.bsp.BspFileGen',
                       args=argv,
                       workunit_name='bsp-gen-invoke',
                       workunit_labels=[WorkUnitLabel.TOOL],
                       distribution=DistributionLocator.cached(),
                       stdin=inf)
