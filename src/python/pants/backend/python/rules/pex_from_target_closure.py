# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional

from pants.backend.python.rules.inject_init import InjectedInitDigest, InjectInitRequest
from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.rules.prepare_chrooted_python_sources import ChrootedPythonSources
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import Digest, DirectoriesToMerge, Snapshot
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.rules import UnionMembership, rule, union
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_root import SourceRootStrippedSources


@union
class PythonResourceTarget:
  """???"""


@dataclass(frozen=True)
class PythonResources:
  snapshot: Snapshot


@dataclass(frozen=True)
class CreatePexFromTargetClosure:
  """Represents a request to create a PEX from the closure of a set of targets."""
  build_file_addresses: BuildFileAddresses
  output_filename: str
  entry_point: Optional[str] = None
  additional_requirements: tuple = ()
  include_source_files: bool = True


@rule(name="Create PEX from targets")
async def create_pex_from_target_closure(request: CreatePexFromTargetClosure,
                                         python_setup: PythonSetup,
                                         union_membership: UnionMembership) -> Pex:
  transitive_hydrated_targets = await Get[TransitiveHydratedTargets](BuildFileAddresses,
                                                                     request.build_file_addresses)
  python_targets = []
  resource_targets = []
  for t in transitive_hydrated_targets.closure:
    if union_membership.is_member(PythonResourceTarget, t.adaptor):
      resource_targets.append(t)
    else:
      python_targets.append(t)

  interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
    adaptors=tuple(t.adaptor for t in python_targets),
    python_setup=python_setup
  )

  if request.include_source_files:
    chrooted_sources = await Get[ChrootedPythonSources](HydratedTargets(python_targets))

    all_resources = await MultiGet(
      Get[PythonResources](PythonResourceTarget, t.adaptor) for t in resource_targets
    )

    stripped_sources_digests = [chrooted_sources.digest] + [
      r.snapshot.directory_digest for r in all_resources
    ]
    sources_digest = await Get[Digest](DirectoriesToMerge(directories=tuple(stripped_sources_digests)))
    inits_digest = await Get[InjectedInitDigest](InjectInitRequest(
      snapshot=(await Get[Snapshot](Digest, sources_digest)),
      matching_source_file_regex=('.*',),
    ))
    all_input_digests = [sources_digest, inits_digest.directory_digest]
    merged_input_files = await Get[Digest](DirectoriesToMerge(directories=tuple(all_input_digests)))
  else:
    merged_input_files = None

  requirements = PexRequirements.create_from_adaptors(
    adaptors=tuple(t.adaptor for t in python_targets),
    additional_requirements=request.additional_requirements
  )

  create_pex_request = CreatePex(
    output_filename=request.output_filename,
    requirements=requirements,
    interpreter_constraints=interpreter_constraints,
    entry_point=request.entry_point,
    input_files_digest=merged_input_files,
  )

  pex = await Get[Pex](CreatePex, create_pex_request)
  return pex


def rules():
  return [
    create_pex_from_target_closure,
  ]
