# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.source.payload_fields import SourcesField
from pants.source.wrapped_globs import FilesetWithSpec
from pants.util.memo import memoized_property


class PythonDistribution(PythonTarget):
  """A Python distribution target that accepts a user-defined setup.py."""

  @classmethod
  def alias(cls):
    return 'python_dist'

  default_sources_globs = [
    '*.c',
    '*.h',
    '*.cpp',
    '*.hpp',
    '*.cxx',
    '*.hxx',
    '*.cc',
  ] + list(PythonLibrary.default_sources_globs)

  def __init__(self, sources=None, provides=None, **kwargs):
    """
    :param sources: Files to "include". Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings. Must include setup.py.
    """
    if provides is not None:
      raise TargetDefinitionException(
        self, "A PythonDistribution may not have a provides parameter "
              "(parameter was: '{}').".format(repr(provides)))

    super(PythonDistribution, self).__init__(
      sources=sources, provides=provides, **kwargs)

    if not 'setup.py' in sources:
      raise TargetDefinitionException(
        self, 'A setup.py in the top-level directory relative to the target definition is required.'
      )
