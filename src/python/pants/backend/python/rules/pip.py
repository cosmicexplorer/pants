# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from pants.backend.python.rules.pex import CreatePex, Pex, PexRequirements
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import RootRule, subsystem_rule, rule
from pants.engine.selectors import Get
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import ensure_relative_file_name
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class PipResolveRequest:
    requirements: PexRequirements


@frozen_after_init
@dataclass(unsafe_hash=True)
class ResolvedRequirement:
    exact_requirement: str
    url: str

    def __init__(self, *, name: str, version: str, url: str) -> None:
        self.exact_requirement = f'{name}=={version}'
        self.url = url


@dataclass(frozen=True)
class PipResolveResult:
    requirements: Tuple[ResolvedRequirement, ...]

    @classmethod
    def from_stdout(cls, stdout: bytes) -> 'PipResolveResult':
        lines = stdout.decode().splitlines()
        assert lines[0] == 'Resolve output:'

        parsed_requirements: List[ResolvedRequirement] = []
        for entry in lines[1:]:
            matched = re.match(r'^([^=]+)==([^ ]+) \(([^\)]+)\)$', entry)
            assert matched, f'line {entry} did not match normal pattern!!!'
            name, version, url = matched.groups()
            parsed_requirements.append(ResolvedRequirement(name=name, version=version, url=url))

        return parsed_requirements


@dataclass(frozen=True)
class Pip:
    pip_pex: Pex

    class Factory(Subsystem):
        options_scope = 'pip'

        @classmethod
        def register_options(cls, register):
            super().register_options(register)
            register('--version',
                     default='20.1.dev0+resolve',
                     help='The version of pip to use to resolve dependencies.')

        @property
        def pip_requirement(self) -> str:
            return f'pip=={self.get_options().pip_version}'

    def make_pip_resolve_execution_request(
        self,
        req: PipResolveRequest,
    ) -> ExecuteProcessRequest:
        pex_filename = self.pip_pex.output_filename
        return ExecuteProcessRequest(
            argv=tuple([
                ensure_relative_file_name(Path(pex_filename)),
                # Max verbosity.
                '-vvv',
                # 'resolve' and '--quickly-parse-sub-requirements' are specifically from the version
                # of pip at 20.1.dev0+resolve. They implement several optimizations.
                'resolve',
                '--quickly-parse-sub-requirements',
                *req.requirements.requirements,
            ]),
            input_files=self.pip_pex.directory_digest,
            description=f"resolve requirements [EXPERIMENTAL!!!] for {req.requirement.requirements}",
        )


@rule
async def resolve_pip(pip_factory: Pip.Factory) -> Pip:
    pip_pex = await Get[Pex](CreatePex(
        output_filename='pip.pex',
        requirements=PexRequirements([pip_factory.pip_requirement])
        entry_point='pip',
    ))
    return Pip(pip_pex)


@rule
async def pip_resolve(
    request: PipResolveRequest,
    pip: Pip,
) -> PipResolveResult:
    pip_exe_req = pip.make_pip_resolve_execution_request(request)
    pip_exe_result = await Get[ExecuteProcessResult](ExecuteProcessRequest, pip_exe_req)
    return PipResolveResult.from_stdout(pip_exe_result.stdout)


def rules():
    return [
        subsystem_rule(Pip.Factory),
        resolve_pip,
        RootRule(PipResolveRequest),
        pip_resolve,
    ]
