# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.interactive_runner import InteractiveRunner, RunLocation
from pants.engine.rules import console_rule
from pants.engine.addressable import BuildFileAddresses
import time


class Run(Goal):
  """Runs a runnable target."""
  name = 'v2-run'


@console_rule
def run(console: Console, runner: InteractiveRunner, build_file_addresses: BuildFileAddresses) -> Run:
  console.write_stdout("Running the `run` goal\n")

  res = runner.run_local_interactive_process(
    argv=["/home/gregs/test.py"],
    run_location=RunLocation.WORKSPACE
  )

  try:
    res.popen.wait()
  except KeyboardInterrupt as e:
    res.popen.kill()

  yield Run(0)


def rules():
  return [run] 
