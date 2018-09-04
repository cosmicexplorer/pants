# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re
from abc import abstractmethod

from pants.util.meta import AbstractClass
from pants.util.objects import convert, convert_default, datatype, not_none


class Spec(AbstractClass):
  """Represents address selectors as passed from the command line.

  Supports `Single` target addresses as well as `Sibling` (:) and `Descendant` (::) selector forms.

  Note: In general, 'spec' should not be a user visible term, it is usually appropriate to
  substitute 'address' for a spec resolved to an address, or 'address selector' if you are
  referring to an unresolved spec string.
  """

  @abstractmethod
  def to_spec_string(self):
    """Returns the normalized string representation of this spec."""


class SingleAddress(datatype([('directory', not_none()), ('name', not_none())]), Spec):
  """A Spec for a single address."""

  def to_spec_string(self):
    return '{}:{}'.format(self.directory, self.name)


class SiblingAddresses(datatype(['directory']), Spec):
  """A Spec representing all addresses located directly within the given directory."""

  def to_spec_string(self):
    return '{}:'.format(self.directory)


class DescendantAddresses(datatype(['directory']), Spec):
  """A Spec representing all addresses located recursively under the given directory."""

  def to_spec_string(self):
    return '{}::'.format(self.directory)


class AscendantAddresses(datatype(['directory']), Spec):
  """A Spec representing all addresses located recursively _above_ the given directory."""

  def to_spec_string(self):
    return '{}^'.format(self.directory)


class Specs(datatype([
    'dependencies',
    ('tags', convert(tuple)),
    ('exclude_patterns', convert_default(tuple)),
])):
  """A collection of Specs representing Spec subclasses, tags and regex filters."""

  def exclude_patterns_memo(self):
    return [re.compile(pattern) for pattern in set(self.exclude_patterns or [])]
