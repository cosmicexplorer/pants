# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.payload import Payload
from pants.source.payload_fields import SourcesField
from pants.source.wrapped_globs import FilesetWithSpec
from pants.util.memo import memoized_property


class PythonDistribution(PythonLibrary):
  """A Python distribution target that accepts a user-defined setup.py."""

  default_sources_globs = [
    '*.c',
    '*.h',
    '*.cpp',
    '*.hpp',
    '*.cxx',
    '*.hxx',
    '*.cc',
  ] + list(PythonLibrary.default_sources_globs)
  default_sources_exclude_globs = PythonLibrary.default_sources_exclude_globs

  @classmethod
  def alias(cls):
    return 'python_dist'

  def __init__(self, sources=None, **kwargs):
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
    super(PythonDistribution, self).__init__(
      sources=sources, **kwargs)

    if not 'setup.py' in sources:
      raise TargetDefinitionException(
        self, 'A setup.py in the top-level directory relative to the target definition is required.'
      )
