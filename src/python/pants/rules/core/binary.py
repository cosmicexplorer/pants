# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import console_rule, rule, union
from pants.engine.selectors import Get
from pants.util.collections import assert_single_element


# TODO(#6004): use proper Logging singleton, rather than static logger.
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BinaryResult:
  buildroot_relative_path: str


class Binary(Goal):
  """Creates a runnable binary."""

  name = 'binary'


@union
class BinaryTarget:
  pass


class BinaryError(Exception):
  """???"""


@console_rule(Binary, [Console, BuildFileAddresses])
def binary(console, addresses):
  try:
    address = assert_single_element(list(addresses))
  except (StopIteration, ValueError):
    raise RunError(f"the `run` goal requires exactly one top-level target! received: {addresses}")
  result = yield Get(BinaryResult, Address, address.to_address())

  console.write_stdout(f"binary produced at: {result.buildroot_relative_path}!")

  yield Binary(0)


@rule(BinaryResult, [HydratedTarget])
def coordinator_of_binaries(target):
  run_result = yield Get(BinaryResult, BinaryTarget, target.adaptor)
  yield run_result


def rules():
  return [
    binary,
    coordinator_of_binaries,
  ]
