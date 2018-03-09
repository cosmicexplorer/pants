# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os
import re

from pants.binaries.binary_tool import BinaryToolBase
from pants.engine.rules import rule
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import datatype


class HostInstalledToolBootstrapError(Exception): pass


# TODO: convert this to v2 when #??? is fixed
# FIXME: merge this with BinaryTool into a common base class
class HostInstalledToolBase(BinaryToolBase):
  """Depend on tools located on the host filesystem and verify that they work.

  Attempt at a structured, autoconf-esque way to depend on tools provided by the
  host filesystem while verifying that they provide the desired
  functionality.

  :API: public
  """

  # NB: gotta set that options_scope
  name = None

  default_tool_path = None

  # If the toolchain is unavailable on the current host, display these simple,
  # complete instructions to obtain the toolchain.
  # TODO: briefly note how to file an issue on github if the instructions fail!
  complete_install_instructions = None

  @classmethod
  def register_options(cls, register):
    super(HostInstalledToolBase, cls).register_options(register)

    register('--host-filesystem-path', advanced=True,
             type=str, default=cls.default_tool_path,
             # TODO: fix this message when remoting happens
             help='Path to this tool on the host filesystem. Path must point '
                  'to an executable file on the filesystem running Pants.')

  def digest(self):
    return hashlib.sha1()

  def validate_host_tool(self, host_path):
    if os.path.isfile(host_path) and os.access(host_path, os.X_OK):
      return host_path
    raise HostInstalledToolBootstrapError(
      "Path '{}' must be an executable file on the host filesystem"
      .format(host_path))

  def host_tool_path(self):
    return self.get_options().host_filesystem_path

  @memoized_method
  def _get_host_tool(self):
    return self.validate_host_tool(self.host_tool_path())

  @memoized_method
  def version(self, context=None):
    return hash_file(self._get_host_tool(), digest=self.digest())

  @memoized_method
  def select_for_version(self, version):
    validated_host_path = self.validate_host_tool()
    return self._binary_util.select_host_installed(
      supportdir=self.get_support_dir(),
      name=self._get_name(),
      version=version,
      host_binary_path=validated_host_path)
