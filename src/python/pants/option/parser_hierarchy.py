# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
from collections import defaultdict

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.config import Config
from pants.option.option_util import create_flag_value_map
from pants.option.parser import Parser
from pants.option.scope import GLOBAL_SCOPE


class InvalidScopeError(Exception):
  pass

_empty_scope_component_re = re.compile(r'\.\.')


def _validate_full_scope(scope):
  if _empty_scope_component_re.search(scope):
    raise InvalidScopeError(
      "full scope '{}' has at least one empty component".format(scope))


def enclosing_scope(scope):
  """Utility function to return the scope immediately enclosing a given scope."""
  _validate_full_scope(scope)
  return scope.rpartition('.')[0]


def all_enclosing_scopes(scope, allow_global=True):
  """Utility function to return all scopes up to the global scope enclosing a
  given scope."""

  _validate_full_scope(scope)

  # TODO(cosmicexplorer): validate scopes here and/or in `enclosing_scope()`
  # instead of assuming correctness.
  def scope_within_range(tentative_scope):
    if tentative_scope is None:
      return False
    if not allow_global and tentative_scope == GLOBAL_SCOPE:
      return False
    return True

  while scope_within_range(scope):
    yield scope
    scope = (None if scope == GLOBAL_SCOPE else enclosing_scope(scope))


class ParserHierarchy(object):
  """A hierarchy of scoped Parser instances.

  A scope is a dotted string: E.g., compile.java. In this example the compile.java scope is
  enclosed in the compile scope, which is enclosed in the global scope (represented by an
  empty string.)
  """

  def __init__(self, env, config, scope_infos, option_tracker):
    # Sorting ensures that ancestors precede descendants.
    scope_infos = sorted(set(list(scope_infos)), key=lambda si: si.scope)
    self._parser_by_scope = {}
    for scope_info in scope_infos:
      scope = scope_info.scope
      parent_parser = (None if scope == GLOBAL_SCOPE else
                       self._parser_by_scope[enclosing_scope(scope)])
      self._parser_by_scope[scope] = Parser(env, config, scope_info, parent_parser,
                                            option_tracker=option_tracker)

  def get_parser_by_scope(self, scope):
    try:
      return self._parser_by_scope[scope]
    except KeyError:
      raise Config.ConfigValidationError('No such options scope: {}'.format(scope))

  def walk(self, callback):
    """Invoke callback on each parser, in pre-order depth-first order."""
    self._parser_by_scope[GLOBAL_SCOPE].walk(callback)

  # TODO: use known_scope_to_info from options instance to do something with
  # deprecated scopes, if necessary
  def fully_parse_scoped_flags(self, scope_to_flags, known_scope_to_info):
    flags_by_correct_scope = defaultdict(list)

    def recurse_scoped_key(parser, key, flag_val):
      scope = parser.scope
      # -ldebug, -x
      if not key.startswith('--'):
        if flag_val is None:
          # -x
          short_flag_reconstructed = key
        else:
          # -ldebug
          short_flag_reconstructed = '{}{}'.format(key, flag_val)
        flags_by_correct_scope[scope].append(short_flag_reconstructed)
        return

      if key.startswith('--no-'):
        # TODO: check here if flag_val is None (that should be asserted -- see
        # below)
        base_key = re.sub(r'^--no-', '--', key)
        has_no = True
      else:
        base_key = key
        has_no = False

      if parser.has_known_arg(base_key):
        if flag_val is None:
          # this still has the --no-
          long_flag_reconstructed = key
        else:
          # TODO: this shouldn't happen if key starts with --no-, we should
          # throw here for that (this is a generally useful thing)
          # TODO: check for options registered with anything but [a-zA-Z\-] in
          # their names?
          long_flag_reconstructed = '{}={}'.format(key, flag_val)
        flags_by_correct_scope[scope].append(long_flag_reconstructed)
        return

      key_split_by_scope_component = re.sub('^--', '', base_key).split('-')
      # TODO: check for 0?
      if len(key_split_by_scope_component) == 0:
        raise Config.ConfigValidationError(
          "LOL: scope='{}', key_split_by_scope_component='{}'"
          .format(scope, key_split_by_scope_component))
      if len(key_split_by_scope_component) == 1:
        # TODO: instead of just failing here, try starting from the ORIGINAL
        # flag, but with the global scope! so './pants compile --test-junit-bar'
        # => {'test.junit': ['--bar']}
        raise Config.ConfigValidationError(
          "idk something: scope='{}', key_split_by_scope_component='{}'"
          .format(scope, key_split_by_scope_component))
      next_scope_component = key_split_by_scope_component[0]
      if scope == GLOBAL_SCOPE:
        new_scope = next_scope_component
      else:
        new_scope = '{}.{}'.format(scope, next_scope_component)
      new_parser = self.get_parser_by_scope(new_scope)
      rest_of_option_name = '-'.join(key_split_by_scope_component[1:])
      if has_no:
        new_key = '--no-{}'.format(rest_of_option_name)
      else:
        new_key = '--{}'.format(rest_of_option_name)
      recurse_scoped_key(new_parser, new_key, flag_val)

    for scope, flags in scope_to_flags.items():
      flag_value_map = create_flag_value_map(flags)
      parser_for_scope = self.get_parser_by_scope(scope)
      for key, flag_val in flag_value_map.items():
        recurse_scoped_key(parser_for_scope, key, flag_val)

    return dict(flags_by_correct_scope)
