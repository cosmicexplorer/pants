# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.build_environment import get_pants_cachedir
from pants.option.custom_types import target_option
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class EnsimeGenSource(Subsystem):

  options_scope = 'ensime-gen-source'

  @classmethod
  def register_options(cls, register):
    super(EnsimeGenSource, cls).register_options(register)

    register('--ensime-gen-binary', type=target_option, default='//:ensime-gen', advanced=True,
             help='The target to use for ensime-gen sources.')

  @memoized_property
  def ensime_gen_binary(self):
    return self.get_options().ensime_gen_binary
