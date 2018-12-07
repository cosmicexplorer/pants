# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.rules import console_rule
from pants.engine.selectors import Select
from pants.rules.core.exceptions import GracefulTerminationException
from pants.subsystem.subsystem import Subsystem


class ListAndDieForTesting(Subsystem):
  """A fast and deadly variant of `./pants list`."""

  options_scope = 'list-and-die-for-testing'


@console_rule(ListAndDieForTesting, [Select(Console), Select(BuildFileAddresses)])
def fast_list_and_die_for_testing(console, addresses):
  for address in addresses.dependencies:
    console.print_stdout(address.spec)
  raise GracefulTerminationException(exit_code=42)


def global_subsystems():
  return [
      ListAndDieForTesting,
    ]


def rules():
  return [
      fast_list_and_die_for_testing,
    ]
