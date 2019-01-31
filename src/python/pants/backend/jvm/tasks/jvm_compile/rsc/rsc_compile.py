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
from pants.engine.fs import Digest, DirectoryToMaterialize, PathGlobs, PathGlobsAndRoot
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


def fast_relpath_collection(collection):
  buildroot = get_buildroot()
  return [fast_relpath_optional(c, buildroot) or c for c in collection]


def stdout_contents(wu):
  if isinstance(wu, FallibleExecuteProcessResult):
    return wu.stdout.rstrip()
  with open(wu.output_paths()['stdout']) as f:
    return f.read().rstrip()


def dump_digest(output_dir, digest):
  safe_file_dump('{}.digest'.format(output_dir),
    '{}:{}'.format(digest.fingerprint, digest.serialized_bytes_length), mode='w')


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
  def __init__(self, runtime_classpath_product, rsc_classpath_product):
    self.rsc_classpath_product = rsc_classpath_product
    self.runtime_classpath_product = runtime_classpath_product

  def add_for_target(self, *args, **kwargs):
    self.runtime_classpath_product.add_for_target(*args, **kwargs)
    self.rsc_classpath_product.add_for_target(*args, **kwargs)


class RscCompileContext(CompileContext):
  def __init__(self,
               target,
               analysis_file,
               classes_dir,
               rsc_mjar_file,
               jar_file,
               log_dir,
               zinc_args_file,
               sources,
               rsc_index_dir):
    super(RscCompileContext, self).__init__(target, analysis_file, classes_dir, jar_file,
                                               log_dir, zinc_args_file, sources)
    self.rsc_mjar_file = rsc_mjar_file
    self.rsc_index_dir = rsc_index_dir

  def ensure_output_dirs_exist(self):
    safe_mkdir(os.path.dirname(self.rsc_mjar_file))
    safe_mkdir(self.rsc_index_dir)


class RscCompile(ZincCompile):
  """Compile Scala and Java code to classfiles using Rsc."""

  _name = 'rsc' # noqa
  compiler_name = 'rsc'

  RSC_COMPATIBLE_TARGET_TAG = 'rsc-compatible'

  def __init__(self, *args, **kwargs):
    super(RscCompile, self).__init__(*args, **kwargs)
    self._metacp_jars_classpath_product = ClasspathProducts(self.get_options().pants_workdir)

  @classmethod
  def implementation_version(cls):
    return super(RscCompile, cls).implementation_version() + [('RscCompile', 171)]

  @classmethod
  def register_options(cls, register):
    super(RscCompile, cls).register_options(register)

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
    return self.do_for_execution_strategy_variant({
      self.HERMETIC: lambda: super(RscCompile, self).get_zinc_compiler_classpath(),
      self.SUBPROCESS: lambda: super(RscCompile, self).get_zinc_compiler_classpath(),
      self.NAILGUN: lambda: self._nailgunnable_combined_classpath,
    })

  class _JvmTargetType(enum(None, ['zinc', 'rsc'])): pass

  _util_core_regexp = re.compile(re.escape('util/util-core'))

  def _identify_rsc_compatible_target(self, target):
    # return self.RSC_COMPATIBLE_TARGET_TAG in target.tags
    return self._util_core_regexp.match(target.address.spec) is not None

  @memoized_method
  def _classify_compile_target(self, target):
    if target.has_sources('.scala'):
      if self._identify_rsc_compatible_target(target):
        if target.has_sources('.java'):
          self.context.log.warn(
            'target {} is marked rsc-compatible but has java sources! compiling with zinc...'
            .format(target))
          target_type = self._JvmTargetType.create('zinc')
        else:
          target_type = self._JvmTargetType.create('rsc')
      else:
        target_type = self._JvmTargetType.create('zinc')
    elif target.has_sources('.java'):
      # This is just a java target.
      target_type = self._JvmTargetType.create('zinc')
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

    for target in targets:
      target_compile_type = self._classify_compile_target(target)
      if target_compile_type is not None:
        rsc_cc, compile_cc = compile_contexts[target]
        target_compile_type.resolve_for_enum_variant({
          'zinc': lambda: self.context.products.get_data('rsc_classpath').add_for_target(
            compile_cc.target,
            confify([compile_cc.jar_file])
          ),
          'rsc': lambda: self.context.products.get_data('rsc_classpath').add_for_target(
            rsc_cc.target,
            confify(to_classpath_entries([rsc_cc.rsc_mjar_file], self.context._scheduler))),
        })

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

  def select(self, target):
    if not isinstance(target, JvmTarget):
      return False
    if self._classify_compile_target(target) is not None:
      return True
    return False

  def _rsc_key_for_target(self, compile_target):
    return self._classify_compile_target(compile_target).resolve_for_enum_variant({
      'zinc': lambda: self._zinc_key_for_target(compile_target),
      'rsc': lambda: 'rsc({})'.format(compile_target.address.spec),
    })

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


        rsc_deps_classpath_unprocessed = _paths_from_classpath(
          self.context.products.get_data('rsc_classpath').get_for_targets(dependencies_for_target),
          collection_type=OrderedSet)

        rsc_classpath_rel = fast_relpath_collection(
          list(rsc_deps_classpath_unprocessed) + self._jvm_lib_jars_abs())
        # # TODO remove non-rsc entries from non_java_rel in a better way
        # rsc_semanticdb_classpath = metacped_jar_classpath_rel + \
        #                              [j for j in non_java_rel if 'compile/rsc/' in j]

        ctx.ensure_output_dirs_exist()

        distribution = self._get_jvm_distribution()
        with Timer() as timer:
          # Outline Scala sources into SemanticDB
          # ---------------------------------------------
          rsc_mjar_file = fast_relpath(ctx.rsc_mjar_file, get_buildroot())

          target_sources = ctx.sources
          args = [
                   '-cp', os.pathsep.join(rsc_classpath_rel),
                   '-d', rsc_mjar_file,
                 ] + target_sources
          sources_snapshot = ctx.target.sources_snapshot(scheduler=self.context._scheduler)
          self._runtool(
            'rsc.cli.Main',
            'rsc',
            args,
            distribution,
            tgt=tgt,
            input_files=tuple(rsc_classpath_rel),
            input_digest=sources_snapshot.directory_digest,
            output_dir=os.path.dirname(rsc_mjar_file))

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
    def rsc_invalid_dep_key(target):
      # Rely on the results of zinc compiles for zinc-compatible targets
      return self._classify_compile_target(target).resolve_for_enum_variant({
        'zinc': lambda: self._zinc_key_for_target(target),
        'rsc': lambda: self._rsc_key_for_target(target),
      })

    self._classify_compile_target(compile_target).resolve_for_enum_variant({
      'zinc': lambda: None,
      'rsc': lambda: rsc_jobs.append(
        Job(
          self._rsc_key_for_target(compile_target),
          functools.partial(
            work_for_vts_rsc,
            ivts,
            compile_context_pair[0]),
          [rsc_invalid_dep_key(target) for target in invalid_dependencies],
          # TODO: It's not clear what compile_context_pair is referring to here.
          self._size_estimator(compile_context_pair[0].sources),
        )
      ),
    })

    # Create the zinc compile jobs.
    # - Scala zinc compile jobs depend on the results of running rsc on the scala target.
    # - Java zinc compile jobs depend on the zinc compiles of their dependencies, because we can't
    #   generate mjars that make javac happy at this point.

    def all_zinc_invalid_dep_keys(invalid_deps):
      for tgt in invalid_deps:
        if self._classify_compile_target(tgt) is not None:
          yield self._zinc_key_for_target(tgt)

    def all_rsc_invalid_dep_keys(invalid_deps):
      for tgt in invalid_deps:
        if self._classify_compile_target(tgt) is not None:
          yield self._rsc_key_for_target(tgt)

    self._classify_compile_target(compile_target).resolve_for_enum_variant({
      'zinc': lambda: zinc_jobs.append(
        Job(
          self._zinc_key_for_target(compile_target),
          functools.partial(
            self._default_work_for_vts,
            ivts,
            compile_context_pair[1],
            'runtime_classpath',
            counter,
            compile_contexts,
            CompositeProductAdder(
              runtime_classpath_product,
              self.context.products.get_data('rsc_classpath'))),
          list(all_zinc_invalid_dep_keys(invalid_dependencies)),
          self._size_estimator(compile_context_pair[1].sources),
          on_failure=ivts.force_invalidate,
        )
      ),
      'rsc': lambda: zinc_jobs.append(
        Job(
          self._zinc_key_for_target(compile_target),
          functools.partial(
            self._default_work_for_vts,
            ivts,
            compile_context_pair[1],
            'rsc_classpath',
            counter,
            compile_contexts,
            runtime_classpath_product),
          [
            self._rsc_key_for_target(compile_target)
          ] + list(all_rsc_invalid_dep_keys(invalid_dependencies)),
          self._size_estimator(compile_context_pair[1].sources),
          # NB: right now, only the last job will write to the cache, because we don't
          #     do multiple cache entries per target-task tuple.
          on_success=ivts.update,
          on_failure=ivts.force_invalidate,
        )
      ),
    })

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
        rsc_mjar_file=os.path.join(rsc_dir, 'm.jar'),
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

    classpath_for_cmd = os.pathsep.join(tool_classpath)
    cmd = [
      distribution.java,
    ]
    cmd.extend(self.get_options().jvm_options)
    cmd.extend(['-cp', classpath_for_cmd])
    cmd.extend([main])
    cmd.extend(args)

    pathglobs = list(tool_classpath)
    pathglobs.extend(f if os.path.isfile(f) else '{}/**'.format(f) for f in input_files)

    if pathglobs:
      root = PathGlobsAndRoot(
      PathGlobs(tuple(pathglobs)),
      text_type(get_buildroot()))
      # dont capture snapshot, if pathglobs is empty
      path_globs_input_digest = self.context._scheduler.capture_snapshots((root,))[0].directory_digest

    if path_globs_input_digest and input_digest:
      epr_input_files = self.context._scheduler.merge_directories(
          (path_globs_input_digest, input_digest))
    else:
      epr_input_files = path_globs_input_digest or input_digest

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
      raise TaskError(res.stderr)

    if output_dir:
      dump_digest(output_dir, res.output_directory_digest)
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
      return self.do_for_execution_strategy_variant({
        self.HERMETIC: lambda: self._runtool_hermetic(
          main, tool_name, args, distribution,
          tgt=tgt, input_files=input_files, input_digest=input_digest, output_dir=output_dir),
        self.SUBPROCESS: lambda: self._runtool_nonhermetic(
          wu, self.tool_classpath(tool_name), main, tool_name, args, distribution),
        self.NAILGUN: lambda: self._runtool_nonhermetic(
          wu, self._nailgunnable_combined_classpath, main, tool_name, args, distribution),
      })

  @memoized_method
  def _jvm_lib_jars_abs(self):
    return self._get_jvm_distribution().find_libs(['rt.jar', 'dt.jar', 'jce.jar', 'tools.jar'])

  @memoized_method
  def _get_jvm_distribution(self):
    # TODO We may want to use different jvm distributions depending on what
    # java version the target expects to be compiled against.
    # See: https://github.com/pantsbuild/pants/issues/6416 for covering using
    #      different jdks in remote builds.
    local_distribution = JvmPlatform.preferred_jvm_distribution([], strict=True)
    if self.execution_strategy == self.HERMETIC and self.get_options().remote_execution_server:
      class HermeticDistribution(object):
        def __init__(self, home_path, distribution):
          self._underlying = distribution
          self._home = home_path

        def find_libs(self, names):
          underlying_libs = self._underlying.find_libs(names)
          return [self._rehome(l) for l in underlying_libs]

        @property
        def java(self):
          return os.path.join(self._home, 'bin', 'java')

        def _rehome(self, l):
          return os.path.join(self._home, l[len(self._underlying.home)+1:])

      return HermeticDistribution('.jdk', local_distribution)
    else:
      return local_distribution

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
