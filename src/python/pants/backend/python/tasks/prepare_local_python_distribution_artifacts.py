# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from future.utils import text_type

from pants.backend.python.tasks.build_local_python_distributions import \
  LocalPythonDistributionWheel
from pants.backend.python.tasks.pex_build_util import is_local_python_dist
from pants.base.build_environment import get_buildroot
from pants.task.task import Task
from pants.util.dirutil import safe_mkdir
from pants.util.fileutil import atomic_copy
from pants.util.memo import memoized_property
from pants.util.objects import datatype


# TODO (NOW): delete this task? what needs the wheels now that we changed the local dists to have
# their own product?
class PrepareLocalPythonDistributionArtifacts(Task):

  @classmethod
  def prepare(cls, options, round_manager):
    super(PrepareLocalPythonDistributionArtifacts, cls).prepare(options, round_manager)
    round_manager.require(LocalPythonDistributionWheel)

  @memoized_property
  def _dist_dir(self):
    return self.get_options().pants_distdir

  def execute(self):
    dist_targets = self.context.targets(is_local_python_dist)

    local_wheels_product = self.context.products.get(LocalPythonDistributionWheel)
    if not local_wheels_product:
      return

    safe_mkdir(self._dist_dir)  # Make sure dist dir is present.

    for dist_tgt in dist_targets:
      # Copy the generated wheel files to the dist folder.
      local_wheel = local_wheels_product.get_single(dist_tgt)
      self.context.log.debug('found local built wheel {}'.format(local_wheel))
      wheel_basename = os.path.basename(local_wheel.path)
      dest_wheel_path = os.path.join(self._dist_dir, wheel_basename)
      atomic_copy(local_wheel.path, dest_wheel_path)

      relative_path_produced_wheel = os.path.relpath(dest_wheel_path, get_buildroot())
      self.context.log.info('created wheel {}'.format(relative_path_produced_wheel))
