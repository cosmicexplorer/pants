# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pex.interpreter import PythonInterpreter

from pants.backend.python.tasks.build_local_python_distributions import \
  LocalPythonDistributionWheel
from pants.backend.python.tasks.pex_build_util import (has_python_requirements,
                                                       is_local_python_dist, is_python_target)
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase


class ResolveRequirements(ResolveRequirementsTaskBase):
  """Resolve external Python requirements."""
  REQUIREMENTS_PEX = 'python_requirements_pex'

  @classmethod
  def product_types(cls):
    return [cls.REQUIREMENTS_PEX]

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)

  def execute(self):
    if not self.context.targets(lambda t: is_python_target(t) or has_python_requirements(t)):
      return
    interpreter = self.context.products.get_data(PythonInterpreter)
    local_wheel_product = self.context.products.get(LocalPythonDistributionWheel)
    local_wheels = [
      local_wheel_product.get_single(dist_tgt)
      for dist_tgt in self.context.targets(is_local_python_dist)
    ]
    pex = self.resolve_requirements(
      interpreter,
      self.context.targets(has_python_requirements),
      local_wheels=local_wheels)
    self.context.products.register_data(self.REQUIREMENTS_PEX, pex)
