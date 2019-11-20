# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os

from pants.backend.codegen.swagger.subsystems.swagger import Swagger
from pants.base.workunit import WorkUnitLabel
from pants.scm.git import Git
from pants.subsystem.subsystem import Subsystem, SubsystemError
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_method

from pants.contrib.go.subsystems.go_distribution import GoDistribution


logger = logging.getLogger(__name__)


class SwaggerGenGo(Subsystem):
  """A compiled swagger plugin that generates Go code.

  For details, see https://github.com/go-swagger/go-swagger
  """
  options_scope = 'swagger-gen-go'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--version', default='v0.21.0', fingerprint=True,
             help='Version of swagger-gen-go plugin to use when generating code')

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (Swagger.scoped(cls), GoDistribution,)

  @memoized_method
  def select(self, context):
    self.get_options()
    workdir = os.path.join(self.get_options().pants_workdir, self.options_scope,
                           'versions', self.get_options().version)
    tool_path = os.path.join(workdir, 'bin/swagger-gen-go')

    if not os.path.exists(tool_path):
      safe_mkdir(workdir, clean=True)

      # Checkout the git repo at a given version. `go get` always gets master.
      repo = Git.clone('https://github.com/go-swagger/go-swagger.git',
                       os.path.join(workdir, 'src/github.com/go-swagger/go-swagger'))
      repo.set_state(self.get_options().version)

      go = GoDistribution.global_instance()
      result, go_cmd = go.execute_go_cmd(
        cmd='install',
        gopath=workdir,
        args=['github.com/go-swagger/go-swagger'],
        workunit_factory=context.new_workunit,
        workunit_labels=[WorkUnitLabel.BOOTSTRAP],
      )

      if result != 0:
        raise SubsystemError('{} failed with exit code {}'.format(go_cmd, result))

    logger.info('Selected {} binary bootstrapped to: {}'.format(self.options_scope, tool_path))
    return tool_path
