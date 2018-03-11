# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class HostConfigurable(object):
  """For tools that need to perform post-install testing or configuration.

  TODO: make it do the installation too (aka "configuration") of things like the
  xcode tools (so all of the host-specific stuff) so they can just subclass
  BinaryToolBase and mix this class in and win
  """
