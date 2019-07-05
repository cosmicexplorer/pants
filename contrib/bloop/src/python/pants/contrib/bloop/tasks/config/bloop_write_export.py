# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import subprocess

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_file_dump, safe_mkdir

from pants.contrib.bloop.tasks.config.bloop_export_config import BloopExportConfig


class BloopWriteExport(NailgunTask):

  @classmethod
  def register_options(cls, register):
    super(BloopWriteExport, cls).register_options(register)

    register('--output-dir', type=str, default='.bloop', advanced=True,
             help='Relative path to the buildroot to write the ensime config to.')
    register('--export-json-output-file', type=str, default='export-wow.json',
             help='Tee the pants export output (which is interpreted by a subprocess) also into '
                  'this file.')

    cls.register_jvm_tool(
      register,
      'bloop-config-gen',
      classpath=[
        JarDependency(
          org='org.pantsbuild',
          name='bloop-config-gen_2.12',
          rev='???',
        ),
      ],
    )

  @classmethod
  def prepare(cls, options, round_manager):
    super(BloopWriteExport, cls).prepare(options, round_manager)
    round_manager.require_data(BloopExportConfig.BloopExport)

  @classmethod
  def product_types(cls):
    return ['bloop_output_dir']

  def execute(self):
    bloop_export = self.context.products.get_data(BloopExportConfig.BloopExport)

    export_result = json.dumps(bloop_export.exported_targets_map, indent=4, separators=(',', ': '))

    safe_file_dump(os.path.join(get_buildroot(), 'idk.json'), payload=export_result, mode='w')

    output_dir = os.path.join(get_buildroot(), self.get_options().output_dir)
    safe_mkdir(output_dir)

    argv = [
      get_buildroot(),
      bloop_export.reported_scala_version,
      self.get_options().pants_distdir,
      output_dir,
      ':'.join(bloop_export.scala_compiler_jars),
    ]

    proc = self.runjava(
      classpath=self.tool_classpath('bloop-config-gen'),
      main='pants.contrib.bloop.config.BloopConfigGen',
      jvm_options=self.get_options().jvm_options,
      args=argv,
      do_async=True,
      workunit_name='bloop-config-gen',
      workunit_labels=[WorkUnitLabel.TOOL],
      stdin=subprocess.PIPE)
    # Write the json export to the subprocess stdin.
    stdout, stderr = proc.communicate(stdin=export_result.encode())
    assert stdout is None
    assert stderr is None
    rc = proc.wait()
    if rc != 0:
      raise TaskError('???', exit_code=rc)

    self.context.products.register_data('bloop_output_dir', output_dir)

    export_output_file = self.get_options().export_json_output_file
    # raise Exception(f'export_output_file: {export_output_file}')
    if export_output_file:
      safe_file_dump(
        os.path.join(get_buildroot(), export_output_file),
        payload=export_result,
        mode='w')
