# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pants.backend.python.rules.create_requirements_pex import MakePexRequest, RequirementsPex
from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.rules.python_run_binary import RunnablePex
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.base.build_environment import get_buildroot
from pants.build_graph.files import Files
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, DirectoryWithPrefixToStrip, MaterializedDirectory
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import BuildFileAddresses, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonBinaryAdaptor
from pants.engine.rules import UnionRule, rule
from pants.engine.selectors import Get
from pants.option.global_options import DistDir
from pants.rules.core.binary import BinaryResult, BinaryTarget
from pants.source.source_root import SourceRoot, SourceRootConfig
from pants.util.strutil import create_path_env_var


@rule(BinaryResult, [PythonBinaryAdaptor, DistDir])
def create_real_python_binary(python_binary_target, dist_dir):
  runnable_pex = yield Get(RunnablePex, PythonBinaryAdaptor, python_binary_target)
  materialized_directory = yield Get(MaterializedDirectory, DirectoryToMaterialize(
    path=dist_dir.path,
    directory_digest=runnable_pex.pex.directory_digest,
  ))
  yield BinaryResult(buildroot_relative_path=materialized_directory.path_bytes.decode('utf-8'))


def rules():
  return [
    create_real_python_binary,
    UnionRule(BinaryTarget, PythonBinaryAdaptor),
  ]
