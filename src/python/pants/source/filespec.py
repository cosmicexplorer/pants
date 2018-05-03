# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
from collections import defaultdict

from pants.util.objects import datatype


def glob_to_regex(pattern):
  """Given a glob pattern, return an equivalent regex expression.
  :param string glob: The glob pattern. "**" matches 0 or more dirs recursively.
                      "*" only matches patterns in a single dir.
  :returns: A regex string that matches same paths as the input glob does.
  """
  out = ['^']
  components = pattern.strip('/').replace('.', '[.]').replace('$','[$]').split('/')
  doublestar = False
  for component in components:
    if len(out) == 1:
      if pattern.startswith('/'):
        out.append('/')
    else:
      if not doublestar:
        out.append('/')

    if '**' in component:
      if component != '**':
        raise ValueError('Invalid usage of "**", use "*" instead.')

      if not doublestar:
        out.append('(([^/]+/)*)')
        doublestar = True
    else:
      out.append(component.replace('*', '[^/]*'))
      doublestar = False

  if doublestar:
    out.append('[^/]*')

  out.append('$')

  return ''.join(out)


class GlobPathMatchingError(Exception): pass


class GlobMatches(datatype(['glob', 'matched_paths'])): pass


def assign_owning_globs(paths, glob_strs):
  """Return a mapping from glob string to owned file.

  The mapping is a list of GlobMatches objects, ordered the same as `glob_strs`.

  Example output:
  [
    GlobMatches('a/*.txt', ['a/file.txt', 'a/other_file.txt']),
    GlobMatches('**/*.c', ['test.c', 'a/b/file.c']),
  ]

  NB: This method will mark glob patterns as empty if glob patterns before the
  "empty" glob in the list also match all the files that the "empty" glob would
  have matched.
  """
  glob_regexes = [(s, re.compile(glob_to_regex(s))) for s in glob_strs]
  matched_globs = defaultdict(list)
  for path in paths:
    cur_matching_glob = None
    for cur_glob_str, cur_glob_rx in glob_regexes:
      if cur_glob_rx.match(path):
        cur_matching_glob = cur_glob_str
        break
    if not cur_matching_glob:
      raise GlobPathMatchingError(
        "None of the provided globs matched the path: {!r}. Globs were: {!r}."
        .format(path, glob_strs))
    matched_globs[cur_matching_glob].append(path)

  matches = [GlobMatches(s, matched_globs[s]) for s in glob_strs]
  return matches


def globs_matches(paths, patterns, exclude_patterns):
  def excluded(path):
    if excluded.regexes is None:
      excluded.regexes = [re.compile(glob_to_regex(ex)) for ex in exclude_patterns]
    return any(ex.match(path) for ex in excluded.regexes)
  excluded.regexes = None
  for pattern in patterns:
    regex = re.compile(glob_to_regex(pattern))
    for path in paths:
      if regex.match(path) and not excluded(path):
        return True
  return False


def matches_filespec(path, spec):
  return any_matches_filespec([path], spec)


def any_matches_filespec(paths, spec):
  if not paths or not spec:
    return False
  exclude_patterns = []
  for exclude_spec in spec.get('exclude', []):
    exclude_patterns.extend(exclude_spec.get('globs', []))
  return globs_matches(paths, spec.get('globs', []), exclude_patterns)
