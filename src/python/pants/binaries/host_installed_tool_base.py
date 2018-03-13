# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os
import re
from abc import abstractmethod

from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import datatype


# TODO: convert this to v2 when #??? is fixed
# FIXME: merge this with BinaryTool into a common base class
class HostInstalledToolBase(Subsystem):
  """Depend on tools located on the host filesystem and verify that they work.

  Attempt at a structured, autoconf-esque way to depend on tools provided by the
  host filesystem while verifying that they provide the desired
  functionality.

  :API: public
  """
  # If the toolchain is unavailable on the current host, display these simple,
  # complete instructions to obtain the toolchain. Must be a string.
  complete_install_instructions = None

  class BootstrapError(Exception): pass

  INSTALL_ERR_WITH_INSTRUCTIONS_BOILERPLATE = """Bootstrap of tool '{name}' failed: {error_desc}

The Pants '{name}' tool requires performing a separate installation process
(described below) before it can be used on this platform. If the below
instructions fail, please determine which project owns the '{name}' tool and
file an issue!

<tell them to use pants github new issue link (provide that) if it's ours!>

{install_instrs}
"""

  def _make_install_instructions(self):
    return self.complete_install_instructions

  def _installation_required_err_msg(self, name, error_desc)
    return self.INSTALL_ERR_WITH_INSTRUCTIONS_BOILERPLATE.format(
      name=name,
      error_desc=error_desc,
      install_instrs=self._make_install_instructions())

  # Subclasses should override this and call super() beforehand.
  @abstractmethod
  def try_get_host_tool(self): pass

  class UserFriendlyBootstrapError(Exception): pass

  @memoized_method
  def _get_host_tool(self):
    try:
      return self.try_get_host_tool()
    except self.BootstrapError as e:
      msg = self._installation_required_err_msg(self._get_name(), e.message)
      raise self.UserFriendlyBootstrapError(msg, e)

  @memoized_method
  def select_for_version(self, version):
    validated_host_tool = self._get_host_tool()

    # TODO: make BinaryUtil handle different types of host-installed
    # tools (e.g. directories) and not just a single binary path.
    return self._binary_util.select_host_installed(
      supportdir=self.get_support_dir(),
      name=self._get_name(),
      version=version,
      host_binary_path=validated_host_tool)


class HostInstalledBinaryTool(HostInstalledToolBase):

  default_tool_path = None

  @classmethod
  def register_options(cls, register):
    super(HostInstalledBinaryTool, cls).register_options(register)

    register('--host-filesystem-path', advanced=True,
             type=str, default=cls.default_tool_path,
             # TODO: fix this message when remoting happens
             help='Path to this tool on the host filesystem. Path must point '
                  'to an executable file on the filesystem running Pants.')

  def try_get_host_tool(self):
    host_path = self.get_options().host_filesystem_path
    if os.path.isfile(host_path) and os.access(host_path, os.X_OK):
      return host_path
    raise HostInstalledToolBase.BootstrapError(
      "Path '{}' must be an executable file on the host filesystem."
      .format(host_path))

  def digest(self):
    return hashlib.sha1()

  @memoized_method
  def version(self):
    return hash_file(self._get_host_tool(), digest=self.digest())
