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

  default_native_sources_globs = '*.c'
  default_native_sources_exclude_globs = None

  @memoized_property
  def _cpp_sources_field(self):
    cpp_sources_field = self.payload.get_field('cpp_sources')
    if cpp_sources_field is not None:
      return cpp_sources_field
    return SourcesField(sources=FilesetWithSpec.empty(self.address.spec_path))

  def cpp_sources_relative_to_target_base(self):
    return self._cpp_sources_field.sources

  @classmethod
  def alias(cls):
    return 'python_dist'

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               cpp_sources=None,
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
      'cpp_sources': self.create_sources_field(cpp_sources, address.spec_path, key_arg='cpp_sources'),
    })
    super(PythonDistribution, self).__init__(
      address=address, payload=payload, sources=sources, **kwargs)

    if not 'setup.py' in sources:
      raise TargetDefinitionException(
        self, 'A setup.py in the top-level directory relative to the target definition is required.'
      )
