# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from pex.pex_info import PexInfo
from pex.version import __version__ as pex_version

from pants.backend.python.rules.pex import CreatePex, Pex, PexRequirements
from pants.backend.python.subsystems.ipex import ipex_launcher
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    DirectoriesToMerge,
    DirectoryWithPrefixToAdd,
    FileContent,
    InputFilesContent,
    Snapshot,
)
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import RootRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.util.pkgutil import get_own_python_source_file_bytes
from pants.python.pex_build_util import PexBuilderWrapper
from pants.python.python_repos import PythonRepos


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IpexRequest:
    underlying_request: CreatePex


@dataclass(frozen=True)
class IpexResult:
    underlying_request: CreatePex


@rule
async def create_ipex(
    request: IpexRequest,
    python_repos: PythonRepos,
    pex_builder_wrapper: PexBuilderWrapper.Factory,
) -> IpexResult:
    logger.debug(f'ipex request: {request}')

    # 1. Create the original pex as-is *without* input files, in order to get the
    #    transitively-resolved requirements from its PEX-INFO.
    orig_request = request.underlying_request

    # Removing the entry point and input files digest means this process execution will be cached
    # even if the source files change! This is useful because resolving large deps such as
    # tensorflow can take multiple minutes when uncached.
    requirements_only_request = dataclasses.replace(
        orig_request,
        entry_point=None,
        input_files_digest=None,
    )
    logger.debug(f'requirements-only request: {requirements_only_request}')
    requirements_only_pex = await Get[Pex](CreatePex, requirements_only_request)

    # 2. Extract its requirements.
    requirements_only_unzipped_info = await Get[ExecuteProcessResult](ExecuteProcessRequest(
        # TODO: make a "hacky local execute process request" type which automatically adds the PATH
        # to the subprocess `env`!
        argv=('unzip', '-p', requirements_only_pex.output_filename, 'PEX-INFO',),
        env={'PATH': os.environ['PATH']},
        input_files=requirements_only_pex.directory_digest,
        description=f'Unzip {requirements_only_pex.output_filename} to extract its PEX-INFO!',
    ))

    # 3. Add the original source files in a subdirectory.
    subdir_sources = await Get[Snapshot](DirectoryWithPrefixToAdd(
        directory_digest=(orig_request.input_files_digest or EMPTY_DIRECTORY_DIGEST),
        prefix=ipex_launcher.APP_CODE_PREFIX))

    # 4. Create IPEX-INFO, BOOTSTRAP-PEX-INFO, and ipex.py.

    # IPEX-INFO: A json mapping interpreted in ipex_launcher.py:
    # {
    #   "code": [<which source files to add to the "hydrated" pex when bootstrapped>],
    #   "resolver_settings": {<which indices to search for requirements from when bootstrapping>},
    # }
    resolver_settings = dict(
        indexes=list(python_repos.indexes),
        # TODO: get self._all_find_links!!!
        find_links=[],
    )
    prefixed_code_paths = subdir_sources.files
    ipex_info = dict(
        code=prefixed_code_paths,
        resolver_settings=resolver_settings,
    )
    ipex_info_file = FileContent(
        path='IPEX-INFO',
        content=json.dumps(ipex_info).encode(),
    )

    # BOOTSTRAP-PEX-INFO: The original PEX-INFO, which should be the PEX-INFO in the hydrated .pex
    #                     file that is generated when the .ipex is first executed.
    requirements_only_pex_info = PexInfo.from_json(requirements_only_unzipped_info.stdout)
    requirements_only_pex_info.entry_point = orig_request.entry_point
    bootstrap_pex_info_file = FileContent(
        path='BOOTSTRAP-PEX-INFO',
        content=requirements_only_pex_info.dump().encode(),
    )

    # ipex.py: The special bootstrap script to hydrate the .ipex with the fully resolved
    #          requirements when it is first executed.
    ipex_launcher_file = FileContent(
        path='ipex.py',
        content=get_own_python_source_file_bytes(ipex_launcher.__name__),
    )

    # 5. Merge all the new injected files, along with the subdirectory of source files, into the new
    # CreatePex input.
    injected_files = await Get[Digest](InputFilesContent([
        ipex_info_file,
        bootstrap_pex_info_file,
        ipex_launcher_file,
    ]))
    merged_input_files = await Get[Digest](DirectoriesToMerge((
        subdir_sources.directory_digest,
        injected_files,
    )))

    # The PEX-INFO we generate shouldn't have any requirements (except pex itself), or they will
    # fail to bootstrap because they were unable to find those distributions. Instead, the .pex file
    # produced when the .ipex is first executed will read and resolve all those requirements from
    # the BOOTSTRAP-PEX-INFO.
    pex_requirement = f'pex=={pex_builder_wrapper.get_options().pex_version}'
    setuptools_requirement = f'setuptools=={pex_builder_wrapper.get_options().setuptools_version}'
    modified_request = dataclasses.replace(
        orig_request,
        requirements=PexRequirements((pex_requirement, setuptools_requirement)),
        entry_point='ipex',
        input_files_digest=merged_input_files,
    )
    logger.debug(f'modified pex creation request: {modified_request}')

    return IpexResult(modified_request)


def rules():
    return [
        RootRule(IpexRequest),
        create_ipex,
        subsystem_rule(PexBuilderWrapper.Factory),
    ]
