# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
from builtins import object, str

from twitter.common.collections import OrderedSet

from pants.engine.rules import TaskRule
from pants.engine.selectors import Get
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.scope import Scope, ScopedOptions, ScopeInfo
from pants.util.objects import datatype


def _construct_subsystem(subsystem_factory):
  scope = subsystem_factory.options_scope
  scoped_options = yield Get(ScopedOptions, Scope(str(scope)))
  yield subsystem_factory.subsystem_cls(scope, scoped_options.options)


class SubsystemFactory(object):
  """A mixin that provides a method that returns an @rule to construct a Subsystem."""

  @property
  def subsystem_cls(self):
    raise NotImplementedError('{} does not define a `subsystem_cls` property.'.format(self))

  @property
  def options_scope(self):
    raise NotImplementedError('{} does not define a `scope` property.'.format(self))

  @classmethod
  def constructor(cls):
    """Returns an @rule (aka TaskRule) that constructs an instance of this Subsystem."""
    snake_scope = cls.options_scope.replace('-', '_')
    partial_construct_subsystem = functools.partial(_construct_subsystem, cls)
    partial_construct_subsystem.__name__ = 'construct_scope_{}'.format(snake_scope)
    return TaskRule(
      cls.subsystem_cls,
      [],
      partial_construct_subsystem,
      input_gets=[Get(ScopedOptions, Scope)],
    )


class SubsystemClientError(Exception): pass


class SubsystemDependency(datatype(['subsystem_cls', 'scope']), SubsystemFactory):
  """Indicates intent to use an instance of `subsystem_cls` scoped to `scope`."""

  def is_global(self):
    return self.scope == GLOBAL_SCOPE

  def options_scope(self):
    """The subscope for options of `subsystem_cls` scoped to `scope`.

    This is the scope that option values are read from when initializing the instance
    indicated by this dependency.
    """
    if self.is_global():
      return self.subsystem_cls.options_scope
    else:
      return self.subsystem_cls.subscope(self.scope)


class SubsystemClientMixin(object):
  """A mixin for declaring dependencies on subsystems.

  Must be mixed in to an Optionable.
  """

  @classmethod
  def subsystem_dependencies(cls):
    """The subsystems this object uses.

    Override to specify your subsystem dependencies. Always add them to your superclass's value.

    Note: Do not call this directly to retrieve dependencies. See subsystem_dependencies_iter().

    :return: A tuple of SubsystemDependency instances.
             In the common case where you're an optionable and you want to get an instance scoped
             to you, call subsystem_cls.scoped(cls) to get an appropriate SubsystemDependency.
             As a convenience, you may also provide just a subsystem_cls, which is shorthand for
             SubsystemDependency(subsystem_cls, GLOBAL SCOPE) and indicates that we want to use
             the global instance of that subsystem.
    """
    return tuple()

  @classmethod
  def subsystem_dependencies_iter(cls):
    """Iterate over the direct subsystem dependencies of this Optionable."""
    for dep in cls.subsystem_dependencies():
      if isinstance(dep, SubsystemDependency):
        yield dep
      else:
        yield SubsystemDependency(dep, GLOBAL_SCOPE)

  class CycleException(Exception):
    """Thrown when a circular subsystem dependency is detected."""

    def __init__(self, cycle):
      message = 'Cycle detected:\n\t{}'.format(' ->\n\t'.join(
        '{} scope: {}'.format(optionable_cls, optionable_cls.options_scope)
        for optionable_cls in cycle))
      super(SubsystemClientMixin.CycleException, self).__init__(message)

  @classmethod
  def known_scope_infos(cls):
    """Yields ScopeInfo for all known scopes for this optionable, in no particular order.

    :raises: :class:`pants.subsystem.subsystem_client_mixin.SubsystemClientMixin.CycleException`
             if a dependency cycle is detected.
    """
    known_scope_infos = set()
    optionables_path = OrderedSet()  #  To check for cycles at the Optionable level, ignoring scope.

    def collect_scope_infos(optionable_cls, scoped_to):
      if optionable_cls in optionables_path:
        raise cls.CycleException(list(optionables_path) + [optionable_cls])
      optionables_path.add(optionable_cls)

      scope = (optionable_cls.options_scope if scoped_to == GLOBAL_SCOPE
               else optionable_cls.subscope(scoped_to))
      scope_info = ScopeInfo(scope, optionable_cls.options_scope_category, optionable_cls)

      if scope_info not in known_scope_infos:
        known_scope_infos.add(scope_info)
        for dep in scope_info.optionable_cls.subsystem_dependencies_iter():
          # A subsystem always exists at its global scope (for the purpose of options
          # registration and specification), even if in practice we only use it scoped to
          # some other scope.
          collect_scope_infos(dep.subsystem_cls, GLOBAL_SCOPE)
          if not dep.is_global():
            collect_scope_infos(dep.subsystem_cls, scope)

      optionables_path.remove(scope_info.optionable_cls)

    collect_scope_infos(cls, GLOBAL_SCOPE)
    return known_scope_infos
