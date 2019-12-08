# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable, Sequence, Set

from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.resolver import resolve_multi
from pex.util import DistributionHelper
from twitter.common.collections import OrderedSet

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.files import Files
from pants.build_graph.target import Target
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_file


_IPEX_PREAMBLE = """\
import json
import os
import sys

from pex import resolver
from pex.common import open_zip
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.util import CacheHelper
from pex.variables import ENV

self = sys.argv[0]
ipex_file = '{}.ipex'.format(os.path.splitext(self)[0])

if not os.path.isfile(ipex_file):
  print('Hydrating {} to {}'.format(self, ipex_file))

  ptex_pex_info = PexInfo.from_pex(self)
  code_root = os.path.join(ptex_pex_info.zip_unsafe_cache, ptex_pex_info.code_hash)
  with open_zip(self) as zf:
    # Populate the pex with the pinned requirements and distribution names & hashes.
    ipex_info = PexInfo.from_json(zf.read('IPEX-INFO'))
    ipex_builder = PEXBuilder(pex_info=ipex_info)

    # Populate the pex with the needed code.
    ptex_info = json.loads(zf.read('PTEX-INFO').decode('utf-8'))
    for path in ptex_info['code']:
      ipex_builder.add_source(os.path.join(code_root, path), path)

  # Perform a fully pinned intransitive resolve to hydrate the install cache (not the
  # pex!).
  resolver_settings = ptex_info['resolver_settings']
  resolved_distributions = resolver.resolve(
    requirements=[str(req) for req in ipex_info.requirements],
    cache=ipex_info.pex_root,
    transitive=False,
    **resolver_settings
  )

  for resolved_dist in resolved_distributions:
    ipex_builder.add_distribution(resolved_dist.distribution)
    ipex_builder.add_requirement(resolved_dist.requirement)
  ipex_builder.build(ipex_file, bytecode_compile=False)

os.execv(ipex_file, [ipex_file] + sys.argv[1:])
"""


def is_python_target(tgt: Target) -> bool:
  # We'd like to take all PythonTarget subclasses, but currently PythonThriftLibrary and
  # PythonAntlrLibrary extend PythonTarget, and until we fix that (which we can't do until
  # we remove the old python pipeline entirely) we want to ignore those target types here.
  return isinstance(tgt, (PythonLibrary, PythonTests, PythonBinary))


def has_python_sources(tgt: Target) -> bool:
  return is_python_target(tgt) and tgt.has_sources()


def is_local_python_dist(tgt: Target) -> bool:
  return isinstance(tgt, PythonDistribution)


def has_resources(tgt: Target) -> bool:
  return isinstance(tgt, Files) and tgt.has_sources()


def has_python_requirements(tgt: Target) -> bool:
  return isinstance(tgt, PythonRequirementLibrary)


def always_uses_default_python_platform(tgt: Target) -> bool:
  return isinstance(tgt, PythonTests)


def may_have_explicit_python_platform(tgt: Target) -> bool:
  return isinstance(tgt, PythonBinary)


def targets_by_platform(targets, python_setup):
  targets_requiring_default_platforms = []
  explicit_platform_settings = defaultdict(OrderedSet)
  for target in targets:
    if always_uses_default_python_platform(target):
      targets_requiring_default_platforms.append(target)
    elif may_have_explicit_python_platform(target):
      for platform in target.platforms if target.platforms else python_setup.platforms:
        explicit_platform_settings[platform].add(target)
  # There are currently no tests for this because they're super platform specific and it's hard for
  # us to express that on CI, but https://github.com/pantsbuild/pants/issues/7616 has an excellent
  # repro case for why this is necessary.
  for target in targets_requiring_default_platforms:
    for platform in python_setup.platforms:
      explicit_platform_settings[platform].add(target)
  return dict(explicit_platform_settings)


def identify_missing_init_files(sources: Sequence[str]) -> Set[str]:
  """Return the list of paths that would need to be added to ensure that every package has
  an __init__.py. """
  packages: Set[str] = set()
  for source in sources:
    if source.endswith('.py'):
      pkg_dir = os.path.dirname(source)
      if pkg_dir and pkg_dir not in packages:
        package = ''
        for component in pkg_dir.split(os.sep):
          package = os.path.join(package, component)
          packages.add(package)

  return {os.path.join(package, '__init__.py') for package in packages} - set(sources)


def _create_source_dumper(builder: PEXBuilder, tgt: Target) -> Callable[[str], None]:
  buildroot = get_buildroot()

  def get_chroot_path(relpath: str) -> str:
    if type(tgt) == Files:
      # Loose `Files`, as opposed to `Resources` or `PythonTarget`s, have no (implied) package
      # structure and so we chroot them relative to the build root so that they can be accessed
      # via the normal Python filesystem APIs just as they would be accessed outside the
      # chrooted environment. NB: This requires we mark the pex as not zip safe so
      # these `Files` can still be accessed in the context of a built pex distribution.
      builder.info.zip_safe = False
      return relpath
    return str(Path(relpath).relative_to(tgt.target_base))

  def dump_source(relpath: str) -> None:
    source_path = str(Path(buildroot, relpath))
    dest_path = get_chroot_path(relpath)
    if has_resources(tgt):
      builder.add_resource(filename=source_path, env_filename=dest_path)
    else:
      builder.add_source(filename=source_path, env_filename=dest_path)

  return dump_source


class PexBuilderWrapper:
  """Wraps PEXBuilder to provide an API that consumes targets and other BUILD file entities."""

  class Factory(Subsystem):
    options_scope = 'pex-builder-wrapper'

    @classmethod
    def register_options(cls, register):
      super(PexBuilderWrapper.Factory, cls).register_options(register)
      register('--setuptools-version', advanced=True, default='40.6.3',
               help='The setuptools version to include in the pex if namespace packages need to be '
                    'injected.')
      register('--generate-ipex', type=bool, default=False, fingerprint=False,
               help='???')

    @classmethod
    def subsystem_dependencies(cls):
      return super(PexBuilderWrapper.Factory, cls).subsystem_dependencies() + (
        PythonRepos,
        PythonSetup,
      )

    @classmethod
    def create(cls, builder, log=None, parent_optionable=None):
      if parent_optionable is None:
        options = cls.global_instance().get_options()
      else:
        options = cls.scoped_instance(parent_optionable).get_options()
      setuptools_requirement = f'setuptools=={options.setuptools_version}'

      log = log or logging.getLogger(__name__)

      return PexBuilderWrapper(builder=builder,
                               python_repos_subsystem=PythonRepos.global_instance(),
                               python_setup_subsystem=PythonSetup.global_instance(),
                               setuptools_requirement=PythonRequirement(setuptools_requirement),
                               log=log,
                               generate_ipex=options.generate_ipex)

  def __init__(self,
               builder,
               python_repos_subsystem,
               python_setup_subsystem,
               setuptools_requirement,
               log,
               generate_ipex=False):
    assert isinstance(builder, PEXBuilder)
    assert isinstance(python_repos_subsystem, PythonRepos)
    assert isinstance(python_setup_subsystem, PythonSetup)
    assert isinstance(setuptools_requirement, PythonRequirement)
    assert log is not None

    self._builder = builder
    self._python_repos_subsystem = python_repos_subsystem
    self._python_setup_subsystem = python_setup_subsystem
    self._setuptools_requirement = setuptools_requirement
    self._log = log

    self._distributions = {}
    self._frozen = False

    self._generate_ipex = generate_ipex
    if self._generate_ipex:
      self._builder.info.zip_safe = False
    self._all_find_links = set()
    self._quickly_parse_sub_requirements = self._generate_ipex

  def add_requirement_libs_from(self, req_libs, platforms=None):
    """Multi-platform dependency resolution for PEX files.

    :param req_libs: A list of :class:`PythonRequirementLibrary` targets to resolve.
    :param platforms: A list of :class:`Platform`s to resolve requirements for.
                      Defaults to the platforms specified by PythonSetup.
    """
    reqs = [req for req_lib in req_libs for req in req_lib.requirements]
    self.add_resolved_requirements(reqs, platforms=platforms)

  def resolve_distributions(self, reqs, platforms=None):
    """Multi-platform dependency resolution.

    :param reqs: A list of :class:`PythonRequirement` to resolve.
    :param platforms: A list of platform strings to resolve requirements for.
                      Defaults to the platforms specified by PythonSetup.
    :returns: List of :class:`pex.resolver.ResolvedDistribution` instances meeting requirements for
              the given platforms.
    """
    deduped_reqs = OrderedSet(reqs)
    find_links = OrderedSet()
    for req in deduped_reqs:
      if req.repository:
        find_links.add(req.repository)

    return self._resolve_multi(deduped_reqs, platforms=platforms, find_links=find_links)

  def add_resolved_requirements(self, reqs, platforms=None, override_ipex_skip=False):
    """Multi-platform dependency resolution for PEX files.

    :param reqs: A list of :class:`PythonRequirement`s to resolve.
    :param platforms: A list of platform strings to resolve requirements for.
                      Defaults to the platforms specified by PythonSetup.
    """
    for resolved_dist in self.resolve_distributions(reqs, platforms=platforms):
      requirement = resolved_dist.requirement
      self._log.debug(f'  Dumping requirement: {requirement}')
      self._builder.add_requirement(str(requirement))

      distribution = resolved_dist.distribution
      dist_loc = os.path.basename(distribution.location)
      if self._generate_ipex and not override_ipex_skip:
        self._log.debug(f'  AVOIDING dumping distribution at .../{dist_loc}!')
      else:
        self._log.debug(f'  Dumping distribution: .../{dist_loc}')
        self.add_distribution(distribution)

  def _resolve_multi(self, requirements, platforms=None, find_links=None):
    python_setup = self._python_setup_subsystem
    python_repos = self._python_repos_subsystem
    platforms = platforms or python_setup.platforms
    find_links = list(find_links) if find_links else []
    find_links.extend(python_repos.repos)

    self._all_find_links |= set(find_links)

    return resolve_multi(
      requirements=[str(req.requirement) for req in requirements],
      interpreters=[self._builder.interpreter],
      indexes=python_repos.indexes,
      find_links=find_links,
      platforms=platforms,
      cache=python_setup.resolver_cache_dir,
      allow_prereleases=python_setup.resolver_allow_prereleases,
      max_parallel_jobs=python_setup.resolver_jobs,
      quickly_parse_sub_requirements=False)

  def add_sources_from(self, tgt: Target) -> None:
    dump_source = _create_source_dumper(self._builder, tgt)
    self._log.debug(f'  Dumping sources: {tgt}')
    for relpath in tgt.sources_relative_to_buildroot():
      try:
        dump_source(relpath)
      except OSError:
        self._log.error(f'Failed to copy {relpath} for target {tgt.address.spec}')
        raise

    if (getattr(tgt, '_resource_target_specs', None) or
      getattr(tgt, '_synthetic_resources_target', None)):
      # No one should be on old-style resources any more.  And if they are,
      # switching to the new python pipeline will be a great opportunity to fix that.
      raise TaskError(
        f'Old-style resources not supported for target {tgt.address.spec}. Depend on resources() '
        'targets instead.'
      )

  def _prepare_inits(self) -> Set[str]:
    chroot = self._builder.chroot()
    sources = chroot.get('source') | chroot.get('resource')
    missing_init_files = identify_missing_init_files(sources)
    if missing_init_files:
      with temporary_file(permissions=0o644) as ns_package:
        ns_package.write(b'__import__("pkg_resources").declare_namespace(__name__)  # type: ignore[attr-defined]')
        ns_package.flush()
        for missing_init_file in missing_init_files:
          self._builder.add_source(filename=ns_package.name, env_filename=missing_init_file)
    return missing_init_files

  def set_emit_warnings(self, emit_warnings):
    self._builder.info.emit_warnings = emit_warnings

  def freeze(self) -> None:
    if self._frozen:
      return
    if self._prepare_inits():
      dist = self._distributions.get('setuptools')
      if not dist:
        self.add_resolved_requirements([self._setuptools_requirement])

    if self._generate_ipex:
      chroot = self._builder.chroot()
      code = [
        f for f in chroot.get('source') | chroot.get('resource')
        if f not in ['__main__.py', PexInfo.PATH]
      ]

      python_setup = self._python_setup_subsystem
      python_repos = self._python_repos_subsystem
      resolver_settings = dict(
        indexes=python_repos.indexes,
        find_links=list(self._all_find_links),
        allow_prereleases=python_setup.resolver_allow_prereleases,
        max_parallel_jobs=python_setup.resolver_jobs,
        # quickly_parse_sub_requirements=self._quickly_parse_sub_requirements,
        quickly_parse_sub_requirements=False,
      )

      ptex_info = dict(code=code, resolver_settings=resolver_settings)
      with temporary_file(permissions=0o644) as ptex_info_file:
        ptex_info_file.write(json.dumps(ptex_info).encode())
        ptex_info_file.flush()
        self._builder.add_resource(filename=ptex_info_file.name, env_filename='PTEX-INFO')

      ipex_info = self._builder.info.copy()
      with temporary_file(permissions=0o644) as ipex_info_file:
        ipex_info_file.write(ipex_info.dump().encode())
        ipex_info_file.flush()
        self._builder.add_resource(filename=ipex_info_file.name, env_filename='IPEX-INFO')

      ptex_launcher = _IPEX_PREAMBLE
      with temporary_file(permissions=0o644) as ptex_launcher_file:
        ptex_launcher_file.write(ptex_launcher.encode())
        ptex_launcher_file.flush()
        self._builder.add_source(filename=ptex_launcher_file.name, env_filename='_ptex_launcher.py')

      self._builder.info.always_write_cache = True
      self._builder.requirements = []
      self._builder.info._requirements = set()

      # self.add_resolved_requirements([PythonRequirement('wheel')], override_ipex_skip=True)
      self.set_entry_point('_ptex_launcher')

    self._builder.freeze(bytecode_compile=False)
    self._frozen = True

  def set_entry_point(self, entry_point):
    self._builder.set_entry_point(entry_point)

  def build(self, safe_path):
    self.freeze()
    self._builder.build(safe_path, bytecode_compile=False, deterministic_timestamp=True)

  def set_shebang(self, shebang):
    self._builder.set_shebang(shebang)

  def add_interpreter_constraint(self, constraint):
    self._builder.add_interpreter_constraint(constraint)

  def add_interpreter_constraints_from(self, constraint_tgts):
    # TODO this would be a great place to validate the constraints and present a good error message
    # if they are incompatible because all the sources of the constraints are available.
    # See: https://github.com/pantsbuild/pex/blob/584b6e367939d24bc28aa9fa36eb911c8297dac8/pex/interpreter_constraints.py
    constraint_tuples = {
      self._python_setup_subsystem.compatibility_or_constraints(tgt.compatibility)
      for tgt in constraint_tgts
    }
    for constraint_tuple in constraint_tuples:
      for constraint in constraint_tuple:
        self.add_interpreter_constraint(constraint)

  def add_direct_requirements(self, reqs):
    for req in reqs:
      self._builder.add_requirement(str(req))

  def add_distribution(self, dist):
    self._builder.add_distribution(dist)
    self._register_distribution(dist)

  def add_dist_location(self, location):
    self._builder.add_dist_location(location)
    dist = DistributionHelper.distribution_from_path(location)
    self._register_distribution(dist)

  def _register_distribution(self, dist):
    self._distributions[dist.key] = dist

  def set_script(self, script):
    self._builder.set_script(script)
