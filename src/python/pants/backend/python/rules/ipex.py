# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from pex.interpreter import PythonInterpreter, PythonIdentity
from pex.interpreter_constraints import matched_interpreters_iter
from pex.pex_info import PexInfo
from pex.version import __version__ as pex_version

from pants.backend.python.rules.download_pex_bin import DownloadedPexBin
from pants.backend.python.rules.pex import CreatePex, Pex, PexRequirements, PexInterpreterConstraints
from pants.backend.python.subsystems.ipex import ipex_launcher
from pants.binaries.binary_tool import BinaryToolFetchRequest
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    DirectoriesToMerge,
    DirectoryWithPrefixToAdd,
    FileContent,
    InputFilesContent,
    SingleFileExecutable,
    Snapshot,
)
from pants.engine.isolated_process import FallibleExecuteProcessResult, ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import RootRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.util.pkgutil import get_own_python_source_file_bytes
from pants.python.pex_build_util import PexBuilderWrapper
from pants.python.python_repos import PythonRepos
from pants.python.python_setup import PythonSetup
from pants.subsystem.subsystem import Subsystem
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import create_path_env_var


logger = logging.getLogger(__name__)


class IpexPexBin(Subsystem):
    options_scope = 'ipex-pex-bin'

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (
            DownloadedPexBin.Factory.scoped(cls),
            PexBuilderWrapper.Factory.scoped(cls),
        )

    @property
    def pex_bin_factory(self):
        return DownloadedPexBin.Factory.scoped_instance(self)

    @property
    def pex_builder_factory(self):
        return PexBuilderWrapper.Factory.scoped_instance(self)


@dataclass(frozen=True)
class IpexPexDownloadedBin:
    exe: SingleFileExecutable


@rule
async def get_hacked_pex(ipex_bin: IpexPexBin) -> IpexPexDownloadedBin:
    snapshot = await Get[Snapshot](BinaryToolFetchRequest(ipex_bin.pex_bin_factory))
    return IpexPexDownloadedBin(SingleFileExecutable(snapshot))


@dataclass(frozen=True)
class IpexRequest:
    underlying_request: CreatePex


@dataclass(frozen=True)
class IpexResult:
    underlying_request: CreatePex


@dataclass(frozen=True)
class InterpreterResolveRequest:
    interpreter_constraints: PexInterpreterConstraints


@dataclass(frozen=True)
class SingleInterpreter:
    identity: PythonIdentity

    def into_interpreter_major_minor_only_constraint(self) -> str:
        interpreter_name = self.identity.requirement.name
        major, minor, _patch = self.identity.version
        major_minor_only_constraint = f"{interpreter_name}=={major}.{minor}.*"
        return major_minor_only_constraint


@rule
def nail_down_single_interpreter(
    req: InterpreterResolveRequest,
    python_setup: PythonSetup,
) -> SingleInterpreter:
    interpreters_iter = PythonInterpreter.iter(paths=python_setup.interpreter_search_paths)
    matching_interpreters = matched_interpreters_iter(
        interpreters_iter, req.interpreter_constraints.constraints)
    min_interpreter = min(matching_interpreters)
    return SingleInterpreter(min_interpreter.identity)


@dataclass(frozen=True)
class PexQuickResolveRequest:
    underlying_request: CreatePex
    single_interpreter: SingleInterpreter


@frozen_after_init
@dataclass(unsafe_hash=True)
class QuickResolveEntry:
    name: str
    version: str
    url: str

    def __init__(self, *, name: str, version: str, url: str) -> None:
        self.name = name
        self.version = version
        self.url = url

    @classmethod
    def from_line(cls, line: str) -> Optional['QuickResolveEntry']:
        matched = re.match(r'^([^=]+)==([^ ]+) \(([^\)]+)\)$', line)
        if not matched:
            return None
        name, version, url = matched.groups()
        return cls(name=name, version=version, url=url)

    def into_json(self) -> Dict[str, str]:
        return dict(name=self.name, version=self.version, url=self.url)


@dataclass(frozen=True)
class PexQuickResolveResult:
    entries: FrozenOrderedSet[QuickResolveEntry]

    @classmethod
    def from_stdout(cls, stdout: bytes) -> 'PexQuickResolveResult':
        parsed_requirements: List[QuickResolveEntry] = []
        for line in stdout.decode().splitlines():
            entry = QuickResolveEntry.from_line(line)
            if entry:
                parsed_requirements.append(entry)
        return cls(parsed_requirements)

    def into_json(self) -> List[Dict[str, str]]:
        return [
            resolved_req.into_json()
            for resolved_req in self.entries
        ]


@rule
async def pex_quick_resolve(
    req: PexQuickResolveRequest,
    python_repos: PythonRepos,
    python_setup: PythonSetup,
    ipex_pex_bin: IpexPexDownloadedBin,
) -> PexQuickResolveResult:
    orig_request = req.underlying_request
    selected_interpreter = req.single_interpreter
    major_minor_only_constraint = selected_interpreter.into_interpreter_major_minor_only_constraint()

    # Get the arguments to provide to pex to run with --resolve-dists-to-stdout!
    pex_resolve_argv = []
    pex_resolve_argv.extend([
        '--no-pypi',
        *(f'--index={url}' for url in python_repos.indexes),
        *(f'--find-links={url}' for url in python_repos.repos),
    ])

    if python_setup.resolver_jobs:
        pex_resolve_argv.extend(["--jobs", python_setup.resolver_jobs])

    if python_setup.manylinux:
        pex_resolve_argv.extend(["--manylinux", python_setup.manylinux])
    else:
        pex_resolve_argv.append("--no-manylinux")

    pex_resolve_argv.extend(orig_request.requirements.requirements)

    # Invoke the experimental `pip resolve` command to get == requirements and matching URLs to
    # download, very quickly.
    # Note that this pex/pip process execution is persistently cached and remotely executable, and will
    # not be re-run if 3rdparty requirements don't change!
    exe_req = ExecuteProcessRequest(
        argv=tuple([
            'python3',
            ipex_pex_bin.exe.exe_filename,
            '--resolve-dists-to-stdout',
            f'--interpreter-constraint={major_minor_only_constraint}',
            # FIXME: get all the desired platforms!!
            '--platform=current',
            *pex_resolve_argv,
        ]),
        input_files=ipex_pex_bin.exe.directory_digest,
        description=f"resolve requirements [EXPERIMENTAL!!!] for {orig_request.requirements.requirements}",
        env={"PATH": create_path_env_var(python_setup.interpreter_search_paths)},
    )
    pex_resolve = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, exe_req)
    assert pex_resolve.exit_code == 1
    result = PexQuickResolveResult.from_stdout(pex_resolve.stdout)
    assert result.entries
    assert len(result.entries) > 0
    return result


@rule
async def create_ipex(
    request: IpexRequest,
    ipex_pex_bin_subsystem: IpexPexBin,
) -> IpexResult:
    logger.debug(f'ipex request: {request}')

    # 1. Create the original pex as-is *without* input files, in order to get the
    #    transitively-resolved requirements from its PEX-INFO.
    orig_request = request.underlying_request

    selected_interpreter = await Get[SingleInterpreter](InterpreterResolveRequest(
        orig_request.interpreter_constraints))
    major_minor_only_constraint = selected_interpreter.into_interpreter_major_minor_only_constraint()
    orig_request = dataclasses.replace(
        orig_request,
        interpreter_constraints=PexInterpreterConstraints([major_minor_only_constraint]),
    )
    pip_high_speed_resolve = await Get[PexQuickResolveResult](PexQuickResolveRequest(
        orig_request,
        single_interpreter=selected_interpreter))

    # 2. Add the original source files in a subdirectory.
    subdir_sources = await Get[Snapshot](DirectoryWithPrefixToAdd(
        directory_digest=(orig_request.input_files_digest or EMPTY_DIRECTORY_DIGEST),
        prefix=ipex_launcher.APP_CODE_PREFIX))

    # 3. Create IPEX-INFO, BOOTSTRAP-PEX-INFO, and ipex.py.
    # IPEX-INFO: A json mapping interpreted in ipex_launcher.py:
    # {
    #   "code": [<which source files to add to the "hydrated" pex when bootstrapped>],
    #   "requirements_with_urls": [<== requirements with urls to download them from>],
    # }
    requirements_with_urls = pip_high_speed_resolve.into_json()
    prefixed_code_paths = subdir_sources.files
    ipex_info = dict(
        code=prefixed_code_paths,
        requirements_with_urls=requirements_with_urls,
    )
    ipex_info_file = FileContent(
        path='IPEX-INFO',
        content=json.dumps(ipex_info).encode(),
    )

    # BOOTSTRAP-PEX-INFO: The original PEX-INFO, which should be the PEX-INFO in the hydrated .pex
    #                     file that is generated when the .ipex is first executed.
    bootstrap_pex_info = PexInfo.default()
    bootstrap_pex_info.entry_point = orig_request.entry_point
    bootstrap_pex_info.add_interpreter_constraint(major_minor_only_constraint)
    bootstrap_pex_info_file = FileContent(
        path='BOOTSTRAP-PEX-INFO',
        content=bootstrap_pex_info.dump().encode(),
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
    options = ipex_pex_bin_subsystem.pex_builder_factory.get_options()
    pex_requirement = f'pex=={options.pex_version}'
    setuptools_requirement = f'setuptools=={options.setuptools_version}'
    modified_request = dataclasses.replace(
        orig_request,
        requirements=PexRequirements((
            pex_requirement,
            setuptools_requirement,
        )),
        entry_point='ipex',
        input_files_digest=merged_input_files,
    )
    logger.debug(f'modified pex creation request: {modified_request}')

    return IpexResult(modified_request)


def rules():
    return [
        subsystem_rule(IpexPexBin),
        get_hacked_pex,
        RootRule(PexQuickResolveRequest),
        pex_quick_resolve,
        RootRule(InterpreterResolveRequest),
        nail_down_single_interpreter,
        RootRule(IpexRequest),
        create_ipex,
    ]
