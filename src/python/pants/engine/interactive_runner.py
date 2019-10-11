# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from enum import Enum
from subprocess import Popen
from pants.engine.rules import RootRule
from tempfile import TemporaryDirectory
from typing import Dict, List


RunLocation = Enum("RunLocation", "WORKSPACE TEMPDIR")


@dataclass(frozen=True)
class InteractiveProcessResult:
  popen: int


class InteractiveRunner:
  def run_local_interactive_process(self,
      argv: List[str],
      env: Dict[str, str] = None,
      run_location: RunLocation = RunLocation.TEMPDIR,
      ) -> InteractiveProcessResult:

    if run_location == RunLocation.TEMPDIR:
      tempdir = TemporaryDirectory()
      cwd = tempdir.name
    else:
      cwd = None

    popen = Popen(args=argv, cwd=cwd)
    return InteractiveProcessResult(popen=popen)


def create_interactive_runner_rules():
  return [RootRule(InteractiveRunner)]
