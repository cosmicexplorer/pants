# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

# python-ansicolors-import-example
from colors import green
# end-python-ansicolors-import-example

def greet(greetee):
  """Given the name, return a greeting for a person of that name."""
  return green('Hello, {}!'.format(greetee))
