# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.subsystems.pex_build_util import identify_missing_init_files
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get


# TODO(#7710): Once this gets fixed, rename this to InitInjectedDigest.
@dataclass(frozen=True)
class InjectedInitDigest:
  directory_digest: Digest


@dataclass(frozen=True)
class InjectInitRequest:
  snapshot: Snapshot
  matching_source_file_regex: Optional[Tuple[str, ...]]


@rule
async def inject_init(req: InjectInitRequest) -> InjectedInitDigest:
  """Ensure that every package has an __init__.py file in it."""
  snapshot = req.snapshot
  missing_init_files = tuple(sorted(identify_missing_init_files(snapshot.files,
                                                                req.matching_source_file_regex)))
  if not missing_init_files:
    new_init_files_digest = EMPTY_DIRECTORY_DIGEST
  else:
    # TODO(7718): add a builtin rule for FilesContent->Snapshot, so that we can avoid using touch
    # and the absolute path and have the engine build the files for us.
    touch_init_request = ExecuteProcessRequest(
      argv=("/usr/bin/touch",) + missing_init_files,
      output_files=missing_init_files,
      description="Inject missing __init__.py files: {}".format(", ".join(missing_init_files)),
      input_files=snapshot.directory_digest,
    )
    touch_init_result = await Get[ExecuteProcessResult](ExecuteProcessRequest, touch_init_request)
    new_init_files_digest = touch_init_result.output_directory_digest
  # TODO(#7710): Once this gets fixed, merge the original source digest and the new init digest
  # into one unified digest.
  return InjectedInitDigest(directory_digest=new_init_files_digest)


@rule
async def inject_init_basic(snapshot: Snapshot) -> InjectedInitDigest:
  return await Get[InjectedInitDigest](InjectInitRequest(
    snapshot=snapshot,
    matching_source_file_regex=None,
  ))


def rules():
  return [
    RootRule(InjectInitRequest),
    inject_init,
    inject_init_basic,
  ]
