# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.option.custom_types import dict_with_files_option, list_option


def is_list_option(kwargs):
  return (kwargs.get('action') == 'append' or kwargs.get('type') == list or
          kwargs.get('type') == list_option)


def is_dict_option(kwargs):
  return kwargs.get('type') in (dict, dict_with_files_option)


def create_flag_value_map(flags):
  """Returns a map of flag -> list of values, based on the given flag strings.

  None signals no value given (e.g., -x, --foo).
  The value is a list because the user may specify the same flag multiple times, and that's
  sometimes OK (e.g., when appending to list-valued options).
  """
  flag_value_map = defaultdict(list)
  for flag in flags:
    key, has_equals_sign, flag_val = flag.partition('=')
    if not has_equals_sign:
      if not flag.startswith('--'):  # '-xfoo' style.
        key = flag[0:2]
        flag_val = flag[2:]
      if not flag_val:
        # Either a short option with no value or a long option with no equals sign.
        # Important so we can distinguish between no value ('--foo') and setting to an empty
        # string ('--foo='), for options with an implicit_value.
        flag_val = None
    flag_value_map[key].append(flag_val)
  return flag_value_map
