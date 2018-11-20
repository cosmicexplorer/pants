# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.build_environment import get_pants_cachedir
from pants.option.custom_types import target_option
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class BspGenSource(Subsystem):

  options_scope = 'bsp-gen-source'

  @classmethod
  def register_options(cls, register):
    super(BspGenSource, cls).register_options(register)

    register('--bsp-gen-binary', type=target_option, default='//:bsp-gen', advanced=True,
             help='The target to use for bsp-gen sources.')

  @memoized_property
  def bsp_gen_binary(self):
    return self.get_options().bsp_gen_binary
