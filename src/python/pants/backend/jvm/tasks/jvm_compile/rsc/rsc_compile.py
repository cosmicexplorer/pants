# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import logging
import os
import re

from future.utils import PY3, text_type
from twitter.common.collections import OrderedSet

from pants.backend.jvm.subsystems.dependency_context import DependencyContext  # noqa
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_compile.compile_context import CompileContext
from pants.backend.jvm.tasks.jvm_compile.execution_graph import Job
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.engine.fs import (EMPTY_DIRECTORY_DIGEST, Digest, DirectoryToMaterialize, PathGlobs,
                             PathGlobsAndRoot)
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.java.jar.jar_dependency import JarDependency
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.contextutil import Timer
from pants.util.dirutil import (fast_relpath, fast_relpath_optional, maybe_read_file,
                                safe_file_dump, safe_mkdir)
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import enum


#
# This is a subclass of zinc compile that uses both Rsc and Zinc to do
# compilation.
# It uses Rsc and the associated tools to outline scala targets. It then
# passes those outlines to zinc to produce the final compile artifacts.
#
#
logger = logging.getLogger(__name__)


def fast_relpath_collection(collection, root=get_buildroot()):
  return [fast_relpath_optional(c, root) or c for c in collection]


def stdout_contents(wu):
  if isinstance(wu, FallibleExecuteProcessResult):
    return wu.stdout.rstrip()
  with open(wu.output_paths()['stdout']) as f:
    return f.read().rstrip()


def write_digest(output_dir, digest):
  safe_file_dump(
    '{}.digest'.format(output_dir),
    mode='w',
    payload='{}:{}'.format(digest.fingerprint, digest.serialized_bytes_length))


def load_digest(output_dir):
  read_file = maybe_read_file('{}.digest'.format(output_dir), binary_mode=False)
  if read_file:
    fingerprint, length = read_file.split(':')
    return Digest(fingerprint, int(length))
  else:
    return None


def _create_desandboxify_fn(possible_path_patterns):
  # Takes a collection of possible canonical prefixes, and returns a function that
  # if it finds a matching prefix, strips the path prior to the prefix and returns it
  # if it doesn't it returns the original path
  # TODO remove this after https://github.com/scalameta/scalameta/issues/1791 is released
  regexes = [re.compile('/({})'.format(p)) for p in possible_path_patterns]
  def desandboxify(path):
    if not path:
      return path
    for r in regexes:
      match = r.search(path)
      if match:
        logger.debug('path-cleanup: matched {} with {} against {}'.format(match, r.pattern, path))
        return match.group(1)
    logger.debug('path-cleanup: no match for {}'.format(path))
    return path
  return desandboxify


def _paths_from_classpath(classpath_tuples, collection_type=list):
  return collection_type(y[1] for y in classpath_tuples)


# write to both rsc classpath and runtime classpath
class CompositeProductAdder(object):
  def __init__(self, *products):
    self.products = products

  def add_for_target(self, *args, **kwargs):
    for product in self.products:
      product.add_for_target(*args, **kwargs)


class RscCompileContext(CompileContext):
  def __init__(self,
               target,
               analysis_file,
               classes_dir,
               rsc_jar_file,
               jar_file,
               log_dir,
               zinc_args_file,
               sources,
               rsc_index_dir):
    super(RscCompileContext, self).__init__(target, analysis_file, classes_dir, jar_file,
                                               log_dir, zinc_args_file, sources)
    self.rsc_jar_file = rsc_jar_file
    self.rsc_index_dir = rsc_index_dir

  def ensure_output_dirs_exist(self):
    safe_mkdir(os.path.dirname(self.rsc_jar_file))
    safe_mkdir(self.rsc_index_dir)


class RscCompile(ZincCompile):
  """Compile Scala and Java code to classfiles using Rsc."""

  _name = 'rsc' # noqa
  compiler_name = 'rsc'

  def __init__(self, *args, **kwargs):
    super(RscCompile, self).__init__(*args, **kwargs)
    self._metacp_jars_classpath_product = ClasspathProducts(self.get_options().pants_workdir)

  @classmethod
  def implementation_version(cls):
    return super(RscCompile, cls).implementation_version() + [('RscCompile', 171)]

  @classmethod
  def product_types(cls):
    return super(RscCompile, cls).product_types() + [
      'rsc_classpath',
      'zinc_scala_classpath_from_rsc',
    ]

  @classmethod
  def register_options(cls, register):
    super(RscCompile, cls).register_options(register)

    register('--rsc-compatible-target-tag', default='rsc-compatible', metavar='<tag>',
             help='Always compile any target with rsc marked with this tag.')
    register('--include-rsc-compatible-target-regexps', type=list, member_type=str,
             metavar='<regexp>',
             help='If a target matches this regexp, compile it with rsc, unless the target also '
                  'matches an exlcude regexp.')
    register('--exclude-rsc-compatible-target-regexps', type=list, member_type=str,
             metavar='<regexp>',
             help="If a target isn't tagged as rsc-compatible, but matches any of these regexps, "
                  "compile it with zinc instead.")

    rsc_toolchain_version = '0.0.0-446-c64e6937'

    cls.register_jvm_tool(
      register,
      'rsc',
      classpath=[
          JarDependency(
              org='com.twitter',
              name='rsc_2.11',
              rev=rsc_toolchain_version,
          ),
      ],
      custom_rules=[
        Shader.exclude_package('rsc', recursive=True),
      ]
    )

  # TODO: allow @memoized_method to convert lists into tuples so they can be hashed!
  @memoized_property
  def _nailgunnable_combined_classpath(self):
    """Register all of the component tools of the rsc compile task as a "combined" jvm tool.

    This allows us to invoke their combined classpath in a single nailgun instance (see #7089 and
    #7092). We still invoke their classpaths separately when not using nailgun, however.
    """
    cp = []
    cp.extend(self.tool_classpath('rsc'))
    # Add zinc's classpath so that it can be invoked from the same nailgun instance.
    cp.extend(super(RscCompile, self).get_zinc_compiler_classpath())
    return cp

  # Overrides the normal zinc compiler classpath, which only contains zinc.
  def get_zinc_compiler_classpath(self):
    return self.execution_strategy_enum.resolve_for_enum_variant({
      self.HERMETIC: lambda: super(RscCompile, self).get_zinc_compiler_classpath(),
      self.SUBPROCESS: lambda: super(RscCompile, self).get_zinc_compiler_classpath(),
      self.NAILGUN: lambda: self._nailgunnable_combined_classpath,
    })()

  class _JvmTargetType(enum(['zinc-scala', 'zinc-java', 'rsc-scala', 'rsc-java'])): pass

  @memoized_property
  def _exclude_regexps(self):
    return [re.compile(pat) for pat in self.get_options().exclude_rsc_compatible_target_regexps]

  @memoized_property
  def _include_regexps(self):
    return [re.compile(pat) for pat in self.get_options().include_rsc_compatible_target_regexps]

  def _identify_rsc_compatible_target(self, target):
    if self.get_options().rsc_compatible_target_tag in target.tags:
      return True
    spec = target.address.spec
    for no_thanks_do_not_use_rsc_regexp in self._exclude_regexps:
      if no_thanks_do_not_use_rsc_regexp.match(target.address.spec):
        self.context.log.debug("Target {} matched regexp '{}' marking it as rsc-incompatible! "
                               "Compiling with zinc..."
                               .format(target, no_thanks_do_not_use_rsc_regexp.pattern))
        return False
    for yes_please_use_rsc_regexp in self._include_regexps:
      if yes_please_use_rsc_regexp.match(spec):
        self.context.log.debug("Target {} matched regexp '{}' -- compiling with rsc!"
                               .format(target, yes_please_use_rsc_regexp.pattern))
        return True
    return False

  @memoized_method
  def _classify_compile_target(self, target):
    if self._identify_rsc_compatible_target(target):
      if target.has_sources('.java'):
      # TODO: Currently rsc header jars are not consumable by javac, so we need to make sure any
      # java compilation occurs after all of its dependencies are compiled with zinc.
        target_type = self._JvmTargetType.create('rsc-java')
      elif target.has_sources('.scala'):
        target_type = self._JvmTargetType.create('rsc-scala')
      else:
        target_type = None
    elif target.has_sources('.java'):
      target_type = self._JvmTargetType.create('zinc-java')
    elif target.has_sources('.scala'):
      target_type = self._JvmTargetType.create('zinc-scala')
    else:
      target_type = None
    return target_type

  def register_extra_products_from_contexts(self, targets, compile_contexts):
    super(RscCompile, self).register_extra_products_from_contexts(targets, compile_contexts)
    def pathglob_for(filename):
      return PathGlobsAndRoot(
        PathGlobs(
          (fast_relpath_optional(filename, get_buildroot()),)),
        text_type(get_buildroot()))

    def to_classpath_entries(paths, scheduler):
      # list of path ->
      # list of (path, optional<digest>) ->
      path_and_digests = [(p, load_digest(os.path.dirname(p))) for p in paths]
      # partition: list of path, list of tuples
      paths_without_digests = [p for (p, d) in path_and_digests if not d]
      if paths_without_digests:
        self.context.log.debug('Expected to find digests for {}, capturing them.'
                               .format(paths_without_digests))
      paths_with_digests = [(p, d) for (p, d) in path_and_digests if d]
      # list of path -> list path, captured snapshot -> list of path with digest
      snapshots = scheduler.capture_snapshots(tuple(pathglob_for(p) for p in paths_without_digests))
      captured_paths_and_digests = [(p, s.directory_digest)
                                    for (p, s) in zip(paths_without_digests, snapshots)]
      # merge and classpath ify
      return [ClasspathEntry(p, d) for (p, d) in paths_with_digests + captured_paths_and_digests]

    def confify(entries):
      return [(conf, e) for e in entries for conf in self._confs]

    # TODO: there's a little bit of duplication here -- in the super() call, ZincCompile will
    # populate classpaths for zinc invocations, but we only need to populate the classpaths from the
    # rsc outputs here because we call register_extra_products_from_contexts() manually in
    # work_for_vts_rsc().
    for target in targets:
      target_compile_type = self._classify_compile_target(target)
      if target_compile_type is not None:
        rsc_cc, compile_cc = compile_contexts[target]
        # TODO: rsc's produced header jars don't yet work with javac, so we introduce the
        # 'zinc_scala_classpath_from_rsc' intermediate product, which contains rsc header jars and
        # zinc output. zinc compilations for java targets then are scheduled strictly after zinc
        # compilations of their dependencies, and only use the 'runtime_classpath' product.
        mixed_zinc_rsc_product = CompositeProductAdder(
          self.context.products.get_data('rsc_classpath'),
          self.context.products.get_data('zinc_scala_classpath_from_rsc'))
        target_compile_type.resolve_for_enum_variant({
          'zinc-java': lambda: None,
          'zinc-scala': lambda: None,
          'rsc-java': lambda: mixed_zinc_rsc_product.add_for_target(
            rsc_cc.target,
            confify(to_classpath_entries([rsc_cc.rsc_jar_file], self.context._scheduler))),
          'rsc-scala': lambda: mixed_zinc_rsc_product.add_for_target(
            rsc_cc.target,
            confify(to_classpath_entries([rsc_cc.rsc_jar_file], self.context._scheduler))),
        })()

  def _is_scala_core_library(self, target):
    return target.address.spec in ('//:scala-library', '//:scala-library-synthetic')

  def create_empty_extra_products(self):
    super(RscCompile, self).create_empty_extra_products()

    compile_classpath = self.context.products.get_data('compile_classpath')
    classpath_product = self.context.products.get_data('rsc_classpath')
    if not classpath_product:
      self.context.products.get_data('rsc_classpath', compile_classpath.copy)
    else:
      classpath_product.update(compile_classpath)

    zinc_nonjava_classpath_product = self.context.products.get_data('zinc_scala_classpath_from_rsc')
    if not zinc_nonjava_classpath_product:
      self.context.products.get_data('zinc_scala_classpath_from_rsc', compile_classpath.copy)
    else:
      zinc_nonjava_classpath_product.update(compile_classpath)

  def select(self, target):
    if not isinstance(target, JvmTarget):
      return False
    if self._classify_compile_target(target) is not None:
      return True
    return False

  def _mixed_zinc_or_rsc_key_for_target_as_dep(self, compile_target):
    return self._classify_compile_target(compile_target).resolve_for_enum_variant({
      'zinc-java': lambda: self._zinc_key_for_target(compile_target),
      'zinc-scala': lambda: self._zinc_key_for_target(compile_target),
      'rsc-java': lambda: self._rsc_key_for_target(compile_target),
      'rsc-scala': lambda: self._rsc_key_for_target(compile_target),
    })()

  def _rsc_key_for_target(self, compile_target):
    return 'rsc({})'.format(compile_target.address.spec)

  def _zinc_key_for_target(self, compile_target):
    return 'zinc({})'.format(compile_target.address.spec)

  def create_compile_jobs(self,
                          compile_target,
                          compile_contexts,
                          invalid_dependencies,
                          ivts,
                          counter,
                          runtime_classpath_product):

    def work_for_vts_rsc(vts, ctx):
      # Double check the cache before beginning compilation
      hit_cache = self.check_cache(vts, counter)
      target = ctx.target
      tgt, = vts.targets

      if not hit_cache:
        counter_val = str(counter()).rjust(counter.format_length(), ' ' if PY3 else b' ')
        counter_str = '[{}/{}] '.format(counter_val, counter.size)
        self.context.log.info(
          counter_str,
          'Rsc-ing ',
          items_to_report_element(ctx.sources, '{} source'.format(self.name())),
          ' in ',
          items_to_report_element([t.address.reference() for t in vts.targets], 'target'),
          ' (',
          ctx.target.address.spec,
          ').')

        # This does the following
        # - collect jar dependencies and metacp-classpath entries for them
        # - collect the non-java targets and their classpath entries
        # - break out java targets and their javac'd classpath entries
        # metacp
        # - metacp the java targets
        # rsc
        # - combine the metacp outputs for jars, previous scala targets and the java metacp
        #   classpath
        # - run Rsc on the current target with those as dependencies

        dependencies_for_target = list(
          DependencyContext.global_instance().dependencies_respecting_strict_deps(target))
        self.context.log.debug('DEPS: {}={}'.format(target, dependencies_for_target))


        rsc_deps_classpath_unprocessed = _paths_from_classpath(
          self.context.products.get_data('rsc_classpath').get_for_targets(dependencies_for_target),
          collection_type=OrderedSet)

        rsc_classpath_rel = fast_relpath_collection(list(rsc_deps_classpath_unprocessed))

        ctx.ensure_output_dirs_exist()

        with Timer() as timer:
          # Outline Scala sources into SemanticDB
          # ---------------------------------------------
          rsc_jar_file = fast_relpath(ctx.rsc_jar_file, get_buildroot())

          sources_snapshot = ctx.target.sources_snapshot(scheduler=self.context._scheduler)

          def hermetic_digest_classpath():
            hermetic_dist = self._hermetic_jvm_distribution()
            jdk_libs_rel, jdk_libs_digest = self._jdk_libs_paths_and_digest(hermetic_dist)
            merged_sources_and_jdk_digest = self.context._scheduler.merge_directories(
              (jdk_libs_digest, sources_snapshot.directory_digest))
            classpath_rel_jdk = rsc_classpath_rel + jdk_libs_rel
            return (merged_sources_and_jdk_digest, classpath_rel_jdk, hermetic_dist)
          def nonhermetic_digest_classpath():
            nonhermetic_dist = self._nonhermetic_jvm_distribution()
            empty_digest = EMPTY_DIRECTORY_DIGEST
            classpath_abs_jdk = rsc_classpath_rel + self._jdk_libs_abs(nonhermetic_dist)
            return (empty_digest, classpath_abs_jdk, nonhermetic_dist)

          (input_digest, classpath_entry_paths, distribution) = self.execution_strategy_enum.resolve_for_enum_variant({
            self.HERMETIC: hermetic_digest_classpath,
            self.SUBPROCESS: nonhermetic_digest_classpath,
            self.NAILGUN: nonhermetic_digest_classpath,
          })()

          target_sources = ctx.sources
          args = [
                   '-cp', os.pathsep.join(classpath_entry_paths),
                   '-d', rsc_jar_file,
                 ] + target_sources

          self._runtool(
            'rsc.cli.Main',
            'rsc',
            args,
            distribution,
            tgt=tgt,
            input_files=tuple(rsc_classpath_rel),
            input_digest=input_digest,
            output_dir=os.path.dirname(rsc_jar_file))

        self._record_target_stats(tgt,
          len(rsc_classpath_rel),
          len(target_sources),
          timer.elapsed,
          False,
          'rsc'
        )
        # Write any additional resources for this target to the target workdir.
        self.write_extra_resources(ctx)

      # Update the products with the latest classes.
      self.register_extra_products_from_contexts([ctx.target], compile_contexts)

    rsc_jobs = []
    zinc_jobs = []

    # Invalidated targets are a subset of relevant targets: get the context for this one.
    compile_target = ivts.target
    compile_context_pair = compile_contexts[compile_target]

    # Create the rsc job.
    # Currently, rsc only supports outlining scala.
    def all_mixed_zinc_rsc_invalid_dep_keys(invalid_deps):
      for tgt in invalid_deps:
        # None can occur for e.g. JarLibrary deps, which we don't need to compile as they are
        # populated in the resolve goal.
        if self._classify_compile_target(tgt) is not None:
          # Rely on the results of zinc compiles for zinc-compatible targets
          yield self._mixed_zinc_or_rsc_key_for_target_as_dep(tgt)

    def make_rsc_job(target, dep_targets):
      return Job(
        self._rsc_key_for_target(target),
        functools.partial(
          work_for_vts_rsc,
          ivts,
          compile_context_pair[0]),
          # The rsc jobs depend on other rsc jobs, and on zinc jobs for zinc-scala targets.
          list(all_mixed_zinc_rsc_invalid_dep_keys(dep_targets)),
          # TODO: It's not clear where compile_context_pair is coming from here.
          self._size_estimator(compile_context_pair[0].sources),
        on_success=ivts.update,
        on_failure=ivts.force_invalidate,
      )

    self._classify_compile_target(compile_target).resolve_for_enum_variant({
      # zinc-scala targets have no rsc job.
      'zinc-java': lambda: None,
      'zinc-scala': lambda: None,
      'rsc-java': lambda: rsc_jobs.append(make_rsc_job(compile_target, invalid_dependencies)),
      'rsc-scala': lambda: rsc_jobs.append(make_rsc_job(compile_target, invalid_dependencies)),
    })()

    # Create the zinc compile jobs.
    # - Scala zinc compile jobs depend on the results of running rsc on the scala target.
    # - Java zinc compile jobs depend on the zinc compiles of their dependencies, because we can't
    #   generate jars that make javac happy at this point.

    def only_zinc_invalid_dep_keys(invalid_deps):
      for tgt in invalid_deps:
        if self._classify_compile_target(tgt) is not None:
          yield self._zinc_key_for_target(tgt)

    # NB: zinc jobs for rsc-compatible targets never depend on their own corresponding rsc jobs,
    # just the rsc jobs of their dependencies!
    def make_zinc_job(target, input_product_key, dep_keys):
      return Job(key=self._zinc_key_for_target(target),
                 fn=functools.partial(
                   self._default_work_for_vts,
                   ivts,
                   compile_context_pair[1],
                   input_product_key,
                   counter,
                   compile_contexts,
                   CompositeProductAdder(
                     runtime_classpath_product,
                     self.context.products.get_data('zinc_scala_classpath_from_rsc'),
                     self.context.products.get_data('rsc_classpath'))),
                 dependencies=list(dep_keys),
                 size=self._size_estimator(compile_context_pair[1].sources),
                 on_success=ivts.update,
                 on_failure=ivts.force_invalidate,
      )

    # TODO: (this is noted in two other places as well) rsc's produced header jars don't yet work
    # with javac, so we introduce the 'zinc_scala_classpath_from_rsc' intermediate product, which
    # contains rsc header jars and zinc output. zinc compilations for java targets then are
    # scheduled strictly after zinc compilations of their dependencies, and only use the
    # 'runtime_classpath' product.
    self._classify_compile_target(compile_target).resolve_for_enum_variant({
      'zinc-java': lambda: zinc_jobs.append(
        make_zinc_job(compile_target, 'runtime_classpath',
                      only_zinc_invalid_dep_keys(invalid_dependencies))),
      # zinc-scala targets will depend on the rsc jobs of rsc-scala targets and zinc jobs of
      # zinc-scala dependencies.
      'zinc-scala': lambda: zinc_jobs.append(
        make_zinc_job(compile_target, 'zinc_scala_classpath_from_rsc',
                      all_mixed_zinc_rsc_invalid_dep_keys(invalid_dependencies))),
      'rsc-java': lambda: zinc_jobs.append(
        make_zinc_job(compile_target, 'runtime_classpath',
                      only_zinc_invalid_dep_keys(invalid_dependencies))),
      'rsc-scala': lambda: zinc_jobs.append(
        make_zinc_job(compile_target, 'zinc_scala_classpath_from_rsc',
                      all_mixed_zinc_rsc_invalid_dep_keys(invalid_dependencies))),
    })()

    return rsc_jobs + zinc_jobs

  def select_runtime_context(self, ccs):
    return ccs[1]

  def create_compile_context(self, target, target_workdir):
    # workdir layout:
    # rsc/
    #   - index/   -- metacp results
    #   - outline/ -- semanticdbs for the current target as created by rsc
    #   - m.jar    -- reified scala signature jar
    # zinc/
    #   - classes/   -- class files
    #   - z.analysis -- zinc analysis for the target
    #   - z.jar      -- final jar for the target
    #   - zinc_args  -- file containing the used zinc args
    sources = self._compute_sources_for_target(target)
    rsc_dir = os.path.join(target_workdir, "rsc")
    zinc_dir = os.path.join(target_workdir, "zinc")
    return [
      RscCompileContext(
        target=target,
        analysis_file=None,
        classes_dir=None,
        jar_file=None,
        zinc_args_file=None,
        rsc_jar_file=os.path.join(rsc_dir, 'm.jar'),
        log_dir=os.path.join(rsc_dir, 'logs'),
        sources=sources,
        rsc_index_dir=os.path.join(rsc_dir, 'index'),
      ),
      CompileContext(
        target=target,
        analysis_file=os.path.join(zinc_dir, 'z.analysis'),
        classes_dir=ClasspathEntry(os.path.join(zinc_dir, 'classes'), None),
        jar_file=ClasspathEntry(os.path.join(zinc_dir, 'z.jar'), None),
        log_dir=os.path.join(zinc_dir, 'logs'),
        zinc_args_file=os.path.join(zinc_dir, 'zinc_args'),
        sources=sources,
      )
    ]

  def _runtool_hermetic(self, main, tool_name, args, distribution, tgt=None, input_files=tuple(), input_digest=None, output_dir=None):
    tool_classpath_abs = self.tool_classpath(tool_name)
    tool_classpath = fast_relpath_collection(tool_classpath_abs)

    cmd = [
      distribution.java,
    ] + self.get_options().jvm_options + [
      '-cp', os.pathsep.join(tool_classpath),
      main,
    ] + args

    pathglobs = list(tool_classpath)
    pathglobs.extend(f if os.path.isfile(f) else '{}/**'.format(f) for f in input_files)

    if pathglobs:
      root = PathGlobsAndRoot(
      PathGlobs(tuple(pathglobs)),
      text_type(get_buildroot()))
      # dont capture snapshot, if pathglobs is empty
      path_globs_input_digest = self.context._scheduler.capture_snapshots((root,))[0].directory_digest

    epr_input_files = self.context._scheduler.merge_directories(
      ((path_globs_input_digest,) if path_globs_input_digest else ())
      + ((input_digest,) if input_digest else ()))

    epr = ExecuteProcessRequest(
      argv=tuple(cmd),
      input_files=epr_input_files,
      output_files=tuple(),
      output_directories=(output_dir,),
      timeout_seconds=15*60,
      description='run {} for {}'.format(tool_name, tgt),
      # TODO: These should always be unicodes
      # Since this is always hermetic, we need to use `underlying_dist`
      jdk_home=text_type(self._zinc.underlying_dist.home),
    )
    res = self.context.execute_process_synchronously_without_raising(
      epr,
      self.name(),
      [WorkUnitLabel.TOOL])

    if res.exit_code != 0:
      raise TaskError(res.stderr, exit_code=res.exit_code)

    if output_dir:
      write_digest(output_dir, res.output_directory_digest)
      self.context._scheduler.materialize_directories((
        DirectoryToMaterialize(
          # NB the first element here is the root to materialize into, not the dir to snapshot
          text_type(get_buildroot()),
          res.output_directory_digest),
      ))
      # TODO drop a file containing the digest, named maybe output_dir.digest
    return res

  # The classpath is parameterized so that we can have a single nailgun instance serving all of our
  # execution requests.
  def _runtool_nonhermetic(self, parent_workunit, classpath, main, tool_name, args, distribution):
    result = self.runjava(classpath=classpath,
                          main=main,
                          jvm_options=self.get_options().jvm_options,
                          args=args,
                          workunit_name=tool_name,
                          workunit_labels=[WorkUnitLabel.TOOL],
                          dist=distribution
    )
    if result != 0:
      raise TaskError('Running {} failed'.format(tool_name))
    runjava_workunit = None
    for c in parent_workunit.children:
      if c.name is tool_name:
        runjava_workunit = c
        break
    # TODO: figure out and document when would this happen.
    if runjava_workunit is None:
      raise Exception('couldnt find work unit for underlying execution')
    return runjava_workunit

  def _runtool(self, main, tool_name, args, distribution,
               tgt=None, input_files=tuple(), input_digest=None, output_dir=None):
    with self.context.new_workunit(tool_name) as wu:
      return self.execution_strategy_enum.resolve_for_enum_variant({
        self.HERMETIC: lambda: self._runtool_hermetic(
          main, tool_name, args, distribution,
          tgt=tgt, input_files=input_files, input_digest=input_digest, output_dir=output_dir),
        self.SUBPROCESS: lambda: self._runtool_nonhermetic(
          wu, self.tool_classpath(tool_name), main, tool_name, args, distribution),
        self.NAILGUN: lambda: self._runtool_nonhermetic(
          wu, self._nailgunnable_combined_classpath, main, tool_name, args, distribution),
      })()

  _JDK_LIB_NAMES = ['rt.jar', 'dt.jar', 'jce.jar', 'tools.jar']

  @memoized_method
  def _jdk_libs_paths_and_digest(self, hermetic_dist):
    jdk_libs_rel, jdk_libs_globs = hermetic_dist.find_libs_path_globs(self._JDK_LIB_NAMES)
    jdk_libs_digest = self.context._scheduler.capture_snapshots(
      (jdk_libs_globs,))[0].directory_digest
    return (jdk_libs_rel, jdk_libs_digest)

  @memoized_method
  def _jdk_libs_abs(self, nonhermetic_dist):
    return nonhermetic_dist.find_libs(self._JDK_LIB_NAMES)

  class _HermeticDistribution(object):
    def __init__(self, home_path, distribution):
      self._underlying = distribution
      self._home = home_path

    def find_libs(self, names):
      underlying_libs = self._underlying.find_libs(names)
      return [os.path.join(self.home, self._unroot_lib_path(l)) for l in underlying_libs]

    def find_libs_path_globs(self, names):
      libs_abs = self._underlying.find_libs(names)
      libs_unrooted = [self._unroot_lib_path(l) for l in libs_abs]
      path_globs = PathGlobsAndRoot(
        PathGlobs(tuple(libs_unrooted)),
        text_type(self._underlying.home))
      return (libs_unrooted, path_globs)

    @property
    def java(self):
      return os.path.join(self._home, 'bin', 'java')

    def _unroot_lib_path(self, path):
      return path[len(self._underlying.home)+1:]

    def _rehome(self, l):
      return os.path.join(self._home, self._unroot_lib_path(l))

  @memoized_method
  def _hermetic_jvm_distribution(self):
    # TODO We may want to use different jvm distributions depending on what
    # java version the target expects to be compiled against.
    # See: https://github.com/pantsbuild/pants/issues/6416 for covering using
    #      different jdks in remote builds.
    local_distribution = JvmPlatform.preferred_jvm_distribution([], strict=True)
    return self._HermeticDistribution('.jdk', local_distribution)

  @memoized_method
  def _nonhermetic_jvm_distribution(self):
    return JvmPlatform.preferred_jvm_distribution([], strict=True)

  def _on_invalid_compile_dependency(self, dep, compile_target):
    """Decide whether to continue searching for invalid targets to use in the execution graph.

    If a necessary dep is a Scala dep and the root is Java, continue to recurse because
    otherwise we'll drop the path between Zinc compile of the Java target and a Zinc
    compile of a transitive Scala dependency.

    This is only an issue for graphs like J -> S1 -> S2, where J is a Java target,
    S1/2 are Scala targets and S2 must be on the classpath to compile J successfully.
    """
    if dep.has_sources('.scala') and compile_target.has_sources('.java'):
      return True
    else:
      return False
