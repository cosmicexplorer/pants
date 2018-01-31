# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_target import PythonTarget
from pants.base.payload import Payload


class PythonDistribution(PythonTarget):
  """A Python distribution target that accepts a user-defined setup.py."""

  default_sources_globs = '*.py'

  @classmethod
  def alias(cls):
    return 'python_dist'

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               c_sources=None,
               **kwargs):
    """
    :param address: The Address that maps to this Target in the BuildGraph.
    :type address: :class:`pants.build_graph.address.Address`
    :param payload: The configuration encapsulated by this target.  Also in charge of most
                    fingerprinting details.
    :type payload: :class:`pants.base.payload.Payload`
    :param sources: Files to "include". Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings. Must include setup.py.
    """
    payload = payload or Payload()
    payload.add_fields({
      'c_sources': self.create_sources_field(sources, address.spec_path, key_arg='c_sources'),
    })
    super(PythonDistribution, self).__init__(
      address=address, payload=payload, sources=sources, **kwargs)

    if not 'setup.py' in sources:
      raise TargetDefinitionException(
        self, 'A setup.py in the top-level directory relative to the target definition is required.'
      )
