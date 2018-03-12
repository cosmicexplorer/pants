# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

from six import string_types

from pants.option.errors import OptionsError
from pants.option.scope import ScopeInfo
from pants.util.meta import AbstractClass


def validate_optionable_scope(s):
  if _scope_matcher.match(s) is None:
    raise OptionsError("""Options scope "{}" is not valid:
    Replace in code with a new scope name consisting of dash-separated-words,
    with words consisting only of lower-case letters and digits.
    """.format(s))


class Optionable(AbstractClass):
  """A mixin for classes that can register options on some scope."""

  # Subclasses must override.
  options_scope = None
  options_scope_category = None

  # Subclasses may override these to specify a deprecated former name for this Optionable's scope.
  # Option values can be read from the deprecated scope, but a deprecation warning will be issued.
  # The deprecation warning becomes an error at the given Pants version (which must therefore be
  # a valid semver).
  deprecated_options_scope = None
  deprecated_options_scope_removal_version = None

  _scope_matcher = re.compile('\A[a-z0-9]+(?:-[a-z0-9]+)*\Z')

  # NB: this default implementation does not allow an empty options_scope!
  # Subclasses (such as GlobalOptionsRegistrar) should override this as
  # necessary.
  @classmethod
  def validate_scope_name_component(cls, scope):
    scope_str = str(scope)
    if cls._scope_matcher.match(scope_str) is None:
      raise OptionsError("""Options scope {} must be a string matching the
      regular expression '{}'.
      """.format(repr(scope_str), cls._scope_matcher.pattern))
    return scope_str

  @classmethod
  def get_validate_optionable_scope(cls):
    scope_str = cls.options_scope
    if scope_str is None or cls.options_scope_category is None:
      raise OptionsError(
        "Class '{}' must set options_scope and options_scope_category."
        .format(cls.__name__))
    return cls.validate_scope_name_component(scope_str)

  @classmethod
  def get_scope_info(cls):
    """Returns a ScopeInfo instance representing this Optionable's options scope."""
    return ScopeInfo(cls.get_validate_optionable_scope(), cls.options_scope_category, cls)

  @classmethod
  def known_scope_infos(cls):
    """Yields ScopeInfo for all known scopes for this optionable, in no particular order.

    Specific Optionable subtypes may override to provide information about other optionables.
    """
    yield cls.get_scope_info()

  @classmethod
  def get_description(cls):
    # First line of docstring.
    return '' if cls.__doc__ is None else cls.__doc__.partition('\n')[0].strip()

  @classmethod
  def register_options(cls, register):
    """Register options for this optionable.

    Subclasses may override and call register(*args, **kwargs).
    """

  @classmethod
  def register_options_on_scope(cls, options):
    """Trigger registration of this optionable's options.

    Subclasses should not generally need to override this method.
    """
    cls.register_options(options.registration_function_for_optionable(cls))

  def __init__(self):
    # Check that the instance's class defines options_scope.
    # Note: It is a bit odd to validate a class when instantiating an object of it. but checking
    # the class itself (e.g., via metaclass magic) turns out to be complicated, because
    # non-instantiable subclasses (such as TaskBase, Task, Subsystem and other domain-specific
    # intermediate classes) don't define options_scope, so we can only apply this check to
    # instantiable classes. And the easiest way to know if a class is instantiable is to hook into
    # its __init__, as we do here. We usually only create a single instance of an Optionable
    # subclass anyway.
    cls = type(self)
    if not isinstance(cls.options_scope, string_types):
      raise NotImplementedError('{} must set an options_scope class-level property.'.format(cls))
