# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os

from abc import abstractproperty
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.tasks.pex_build_util import dump_requirements
from pants.backend.python.tasks.wrapped_pex import WrappedPEX
from pants.base.build_environment import get_pants_cachedir
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_concurrent_creation
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class ExecutablePexTool(Subsystem):
  """???"""
  # TODO: ???
  python_requirements = None
  entry_point = None
  cache_subdir = None
  pex_filename = None

  @classmethod
  def implementation_version(cls):
    return super(ExecutablePexTool, cls).implementation_version() + [('ExecutablePexTool', 0)]

  class PexBinary(datatype([('wrapped_pex', WrappedPEX)])): pass

  def bootstrap_pex_tool(self, interpreter=None):
    if interpreter is None:
      interpreter = PythonInterpreter.get()

    pex_info = PexInfo.default()
    if self.entry_point:
      pex_info.entry_point = self.entry_point

    pex_bootstrap_dir = os.path.join(get_pants_cachedir(), self.cache_subdir)
    pex_path = os.path.join(pex_bootstrap_dir, self.pex_filename)

    if os.path.exists(pex_path):
      wrapped_pex = WrappedPEX(PEX(pex_path, interpreter))
    else:
      with safe_concurrent_creation(pex_path) as safe_path:
        builder = PEXBuilder(safe_path, interpreter, pex_info=pex_info)
        reqs = [PythonRequirement(req) for req in self.python_requirements]
        dump_requirements(builder, interpreter, reqs, logger)
        builder.freeze()
      wrapped_pex = WrappedPEX(PEX(pex_path, interpreter))

    return self.PexBinary(wrapped_pex)
