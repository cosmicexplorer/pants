# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.util.memo import memoized_property


class NativeToolchainComponentMixin(object):

  @memoized_property
  def config(self):
    return self.get_config()

  @abstractmethod
  def get_config(self): pass
