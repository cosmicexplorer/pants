# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import subprocess

from pants.backend.codegen.swagger.subsystems.swagger import Swagger
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.option.custom_types import target_option
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from twitter.common.collections import OrderedSet

from pants.contrib.go.subsystems.swagger_gen_go import SwaggerGenGo
from pants.contrib.go.targets.go_swagger_library import GoSwaggerGenLibrary, GoSwaggerLibrary


class GoSwaggerGen(SimpleCodegenTask):

  sources_globs = ('**/*',)

  _NAMESPACE_PARSER = re.compile(r'^\s*option\s+go_package\s*=\s*"([^\s]+)"\s*;', re.MULTILINE)
  _PACKAGE_PARSER = re.compile(r'^\s*package\s+([^\s]+)\s*;', re.MULTILINE)

  @classmethod
  def register_options(cls, register):
    super().register_options(register)

    register('--import-target', type=target_option, fingerprint=True,
             help='Target that will be added as a dependency of swagger-generated Go code.')
    register('--swagger-plugins', type=list, fingerprint=True,
             help='List of swagger plugins to activate.  E.g., grpc.')

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (Swagger.scoped(cls), SwaggerGenGo,)

  @memoized_property
  def _swagger(self):
    return Swagger.scoped_instance(self).select(context=self.context)

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    import_target = self.get_options().import_target
    if import_target is None:
      raise TaskError('Option import_target in scope {} must be set.'.format(
        self.options_scope))
    return self.context.resolve(import_target)

  def synthetic_target_type(self, target):
    return GoSwaggerGenLibrary

  def is_gentarget(self, target):
    return isinstance(target, GoSwaggerLibrary)

  @classmethod
  def product_types(cls):
    return ['go']

  def execute_codegen(self, target, target_workdir):
    target_cmd = [self._swagger]

    swagger_gen_go = SwaggerGenGo.global_instance().select(self.context)
    env = os.environ.copy()
    env['PATH'] = ':'.join([os.path.dirname(swagger_gen_go), env['PATH']])

    bases = OrderedSet(tgt.target_base for tgt in target.closure() if self.is_gentarget(tgt))

    outdir = os.path.join(target_workdir, 'src', 'go')
    safe_mkdir(outdir)
    swagger_plugins = self.get_options().swagger_plugins + list(target.swagger_plugins)
    if swagger_plugins:
      go_out = 'plugins={}:{}'.format('+'.join(swagger_plugins), outdir)
    else:
      go_out = outdir
    target_cmd.append('--go_out={}'.format(go_out))

    all_sources = list(target.sources_relative_to_buildroot())
    for source in all_sources:
      file_cmd = target_cmd + [os.path.join(get_buildroot(), source)]
      with self.context.new_workunit(name=source,
                                     labels=[WorkUnitLabel.TOOL],
                                     cmd=' '.join(file_cmd)) as workunit:
        self.context.log.info(' '.join(file_cmd))
        result = subprocess.call(file_cmd,
                                 env=env,
                                 stdout=workunit.output('stdout'),
                                 stderr=workunit.output('stderr'))
        if result != 0:
          raise TaskError('{} ... exited non-zero ({})'.format(self._swagger, result))

  @property
  def _copy_target_attributes(self):
    return [a for a in super()._copy_target_attributes if a != 'provides']

  def synthetic_target_dir(self, target, target_workdir):
    all_sources = list(target.sources_relative_to_buildroot())
    source = all_sources[0]
    namespace = self._get_go_namespace(source)
    return os.path.join(target_workdir, 'src', 'go', namespace)

  @classmethod
  def _get_go_namespace(cls, source):
    with open(source, 'r') as fh:
      data = fh.read()
    namespace = cls._NAMESPACE_PARSER.search(data)
    if not namespace:
      namespace = cls._PACKAGE_PARSER.search(data)
    return namespace.group(1)
