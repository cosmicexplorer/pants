# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from twitter.common.collections import maybe_list

from pants.backend.python.targets.python_target import PythonTarget
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.util.memo import memoized_classproperty


class PythonDistribution(PythonTarget):
  """A Python distribution target that accepts a user-defined setup.py."""

  default_sources_globs = '*.py'

  @classmethod
  def alias(cls):
    return 'python_dist'

  @memoized_classproperty
  def _non_v2_target_kwargs(cls):
    return super()._non_v2_target_kwargs | frozenset(['has_native_sources'])

  def __init__(self,
               address=None,
               payload=None,
               setup_requires=None,
               **kwargs):
    """
    :param address: The Address that maps to this Target in the BuildGraph.
    :type address: :class:`pants.build_graph.address.Address`
    :param payload: The configuration encapsulated by this target.  Also in charge of most
                    fingerprinting details.
    :type payload: :class:`pants.base.payload.Payload`
    :param sources: Files to "include". Paths are relative to the
      BUILD file's directory.
    :type sources: :class:`twitter.common.dirutil.Fileset` or list of strings. Must include
                   setup.py.
    :param list setup_requires: A list of python requirements to provide during the invocation of
                                setup.py.
    """
    payload = payload or Payload()
    payload.add_fields({
      'setup_requires': PrimitiveField(maybe_list(setup_requires or ()))
    })
    super().__init__(
      address=address, payload=payload, **kwargs)

  @property
  def has_native_sources(self):
    return self.has_sources(extension=tuple(self.native_source_extensions))

  @property
  def setup_requires(self):
    return self.payload.setup_requires
