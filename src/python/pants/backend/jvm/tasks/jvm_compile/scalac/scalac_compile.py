# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import errno
import logging
import os
import re
import textwrap
from contextlib import closing
from hashlib import sha1
from xml.etree import ElementTree

from future.utils import text_type

from pants.backend.jvm.subsystems.graal import GraalCE
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin
from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.engine.fs import DirectoryToMaterialize, PathGlobs, PathGlobsAndRoot, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, ProcessExecutionFailure
from pants.java.distribution.distribution import DistributionLocator
from pants.java.jar.jar_dependency import JarDependency
from pants.util.contextutil import open_zip
from pants.util.dirutil import fast_relpath, fast_relpath_optional, safe_open
from pants.util.memo import memoized_classmethod, memoized_method, memoized_property
from pants.util.meta import classproperty


logger = logging.getLogger(__name__)


# Well known metadata file required to register scalac plugins with nsc.
_SCALAC_PLUGIN_INFO_FILE = 'scalac-plugin.xml'


def fast_relpath_collection(collection, root=get_buildroot()):
  return [fast_relpath_optional(c, root) or c for c in collection]


class ScalacCompile(JvmCompile):
  """Compile Scala code using Scalac."""

  _name = 'scala'
  compiler_name = 'scalac'

  # NB: currently, we have just copied over the methods from jvm_compile.py which javac_compile.py
  # implements, but using the relevant scala logic from zinc_compile.py!
  @staticmethod
  def _write_scalac_plugin_info(resources_dir, scalac_plugin_target):
    scalac_plugin_info_file = os.path.join(resources_dir, _SCALAC_PLUGIN_INFO_FILE)
    with safe_open(scalac_plugin_info_file, 'w') as f:
      f.write(textwrap.dedent("""
        <plugin>
          <name>{}</name>
          <classname>{}</classname>
        </plugin>
      """.format(scalac_plugin_target.plugin, scalac_plugin_target.classname)).strip())

  @classmethod
  def get_args_default(cls, bootstrap_option_values):
    return ('-encoding', 'UTF-8', '-g:vars',)

  @classmethod
  def get_warning_args_default(cls):
    return ('-deprecation', '-unchecked', '-Xlint',)

  @classmethod
  def get_no_warning_args_default(cls):
    return ('-nowarn', '-Xlint:none',)

  @classproperty
  def get_fatal_warnings_enabled_args_default(cls):
    return ('-Xfatal-warnings',)

  @classmethod
  def register_options(cls, register):
    super(ScalacCompile, cls).register_options(register)

    cls.register_jvm_tool(register, 'native-image-stubs', classpath=[
      JarDependency(org='org.pantsbuild', name='native-image-stubs', rev='???'),
    ])

  # TODO: move these to the top of the file!
  @classmethod
  def subsystem_dependencies(cls):
    return super(ScalacCompile, cls).subsystem_dependencies() + (ScalaPlatform.scoped(cls),)

  @memoized_property
  def _scala(self):
    # TODO: this might need to be global -- we'll see when something breaks!
    return ScalaPlatform.scoped_instance(self)

  @classmethod
  def product_types(cls):
    return ['runtime_classpath']

  def __init__(self, *args, **kwargs):
    super(ScalacCompile, self).__init__(*args, **kwargs)
    # Sets self._dist!
    self.set_distribution(jdk=True)

  def select(self, target):
    # TODO: figure out scala_library()s with java_sources= (probably just call into JavacCompile?)!
    return isinstance(target, JvmTarget)

  def select_source(self, source_file_path):
    return source_file_path.endswith('.java') or source_file_path.endswith('.scala')

  @memoized_property
  def _scalac_cp_entries(self):
    return self._scala.compiler_classpath_entries(self.context.products, self.context._scheduler)

  def write_extra_resources(self, compile_context):
    target = compile_context.target
    if isinstance(target, ScalacPlugin):
      self._write_scalac_plugin_info(compile_context.classes_dir.path, target)

  def compile(self, ctx, args, dependency_classpath, upstream_analysis,
              settings, compiler_option_sets, zinc_file_manager,
              javac_plugin_map, scalac_plugin_map):
    user_cp_abs = (ctx.classes_dir.path,) + tuple(ce.path for ce in dependency_classpath)

    if self.get_options().capture_classpath:
      self._record_compile_classpath(user_cp_abs, ctx.target, ctx.classes_dir.path)

    # NB: For hermetic, we want a relative path.
    classes_dir = fast_relpath(ctx.classes_dir.path, get_buildroot())

    output_dir = self.execution_strategy_enum.resolve_for_enum_variant({
      self.HERMETIC: '.',
      self.HERMETIC_WITH_NAILGUN: '.',
      self.SUBPROCESS: ctx.classes_dir.path,
      self.NAILGUN: ctx.classes_dir.path,
      self.GRAAL: classes_dir,
    })

    # Search for scalac plugins on the classpath.
    # Note that:
    # - We also search in the extra scalac plugin dependencies, if specified.
    # - In scala 2.11 and up, the plugin's classpath element can be a dir, but for 2.10 it must be
    #   a jar.  So in-repo plugins will only work with 2.10 if --use-classpath-jars is true.
    # - We exclude our own classes_dir/jar_file, because if we're a plugin ourselves, then our
    #   classes_dir doesn't have scalac-plugin.xml yet, and we don't want that fact to get
    #   memoized (which in practice will only happen if this plugin uses some other plugin, thus
    #   triggering the plugin search mechanism, which does the memoizing).
    scalac_plugin_search_classpath = (
      (set(user_cp_abs) | set(self.scalac_plugin_classpath_elements())) -
      {ctx.classes_dir.path, ctx.jar_file.path}
    )
    scalac_plugin_args = self._scalac_plugin_args(scalac_plugin_map, scalac_plugin_search_classpath)

    extra_args = self._args
    compiler_option_sets_args = self.get_merged_args_for_compiler_option_sets(compiler_option_sets)
    jvm_platform_settings_args = self._get_jvm_platform_arguments(settings)

    trailing_args = (
      scalac_plugin_args
      + extra_args
      + compiler_option_sets_args
      + jvm_platform_settings_args
      + args
    )

    scalac_merged_args = [
      '-classpath', ':'.join(fast_relpath_collection(user_cp_abs)),
      '-d', output_dir,
    ]  + trailing_args + ctx.sources

    jvm_options = self._jvm_options

    return self.execution_strategy_enum.resolve_for_enum_variant({
      # TODO: the hermetic strategies reference variables that don't exist, that we should also crib
      # from compile() in zinc_compile.py! Also see the _execute_hermetic_compile() method in
      # javac_compile.py!
      self.HERMETIC: lambda: self._compile_hermetic(
        jvm_options, ctx, classes_dir, scalac_merged_args, dependency_classpath,
        self._scalac_cp_entries, with_nailgun=False),
      self.HERMETIC_WITH_NAILGUN: lambda: self._compile_hermetic(
        jvm_options, ctx, classes_dir, scalac_merged_args, dependency_classpath,
        self._scalac_cp_entries, with_nailgun=True),
      self.SUBPROCESS: lambda: self._compile_nonhermetic(
        jvm_options, scalac_merged_args),
      self.NAILGUN: lambda: self._compile_nonhermetic(
        jvm_options, scalac_merged_args),
      self.GRAAL: lambda: self._compile_graal(
        jvm_options, ctx, classes_dir, scalac_merged_args, dependency_classpath),
    })()

  class ScalacCompileError(TaskError):
    """An exception type specifically to signal a failed scalac execution."""

  @memoized_method
  def classpath_fingerprint(self, cp_entries):
    hasher = sha1()
    # TODO: there is definitely a better way to get the hash of a set of digests than this!
    cp_entry_digests= sorted(repr(cp.directory_digest) for cp in cp_entries)
    for digest_hash in cp_entry_digests:
      hasher.update(digest_hash.encode('utf-8'))
    return text_type(hasher.hexdigest())

  @memoized_property
  def _scalac_classpath_fingerprint(self):
    return self.classpath_fingerprint(tuple(self._scalac_cp_entries))

  def scalac_bootstrap_classpath_paths(self):
    # Entries for the compiler and library: see
    # https://www.scala-lang.org/files/archive/nightly/docs/manual/html/scalac.html.
    # Note that we do not (yet) use the -bootstrap-classpath option for this!
    return [cp.path for cp in self._scalac_cp_entries]

  @memoized_method
  def cp_entries_for_tool(self, key):
    tool_cp = self.tool_classpath(key)
    cp_rel = fast_relpath_collection(tool_cp)
    return self._memoized_classpath_entries_with_digests(tuple(cp_rel), self.context._scheduler)

  # TODO: this allows us to remote the graal compilation -- do we want to do that though? (I think
  # so!?
  @memoized_property
  def _substitutions_cp_entries(self):
    return self.cp_entries_for_tool('native-image-stubs')

  # TODO: is this still used?
  @memoized_method
  def _memoized_classpath_entries_with_digests(self, classpath_paths, scheduler):
    snapshots = scheduler.capture_snapshots(tuple(
      PathGlobsAndRoot(PathGlobs([path]), get_buildroot())
      for path in classpath_paths
    ))
    return [ClasspathEntry(path, snapshot) for path, snapshot in list(zip(classpath_paths, snapshots))]

  @memoized_method
  def _capture_dependency_classpath(self, classpath_entries, scheduler):
    without_dep_classpath = []
    with_cp = []
    for entry in classpath_entries:
      if entry.directory_digest:
        with_cp.append(entry)
      else:
        # TODO: every entry should have a digest!! also consider memoizing individual entries if
        # we're spending a lot of time snapshotting!
        logger.warning(
          "ClasspathEntry {} didn't have a Digest, so we're recapturing it for hermetic execution"
          .format(entry))
        without_dep_classpath.append(entry)
    now_captured_empty_entries = self._memoized_classpath_entries_with_digests(
      tuple(fast_relpath_collection(cp.path for cp in without_dep_classpath)), scheduler)
    return with_cp + now_captured_empty_entries

  def _filter_scalac_args(self, args):
    valid_args = []
    prev_was_continued_invalid = False
    for arg in args:
      if prev_was_continued_invalid:
        prev_was_continued_invalid = False
        continue
      elif re.match(r'^-C', arg):
        continue
      elif arg in ['-file-filter', '-log-level']:
        prev_was_continued_invalid = True
        continue
      else:
        valid_args.append(re.sub(r'^-S', '', arg))
    return valid_args

  def _compile_graal(self,  jvm_options, ctx, classes_dir, scalac_args, dependency_classpath):
    scalac_args = self._filter_scalac_args(scalac_args)
    boot_cp_entries = self._memoized_classpath_entries_with_digests(
      tuple(self.scalac_bootstrap_classpath_paths()),
      self.context._scheduler)
    # TODO: `graal_rt` provides the rt.jar necessary to run native images. We can provide it through
    # the .jdk symlink with just .jdk/jre/lib/rt.jar, but since it's graal-specific, it seems
    # reasonable to "pin" it with its own directory digest (this also makes it remotable, I think).
    graal_rt = self._graal_ce.runtime_jar_cp_entry(self.context._scheduler)
    args_with_graal_bootstrap_cp = [
      # Join relative paths to elements of the bootstrap classpath (these will be their paths in the
      # sandbox).
      '-Dscala.boot.class.path={}'.format(':'.join(
        [cp.path for cp in boot_cp_entries]
        + [graal_rt.path]
      )),
      '-Dscala.usejavacp=true',
    ] + scalac_args
    build_digests = [cp.directory_digest.directory_digest for cp in boot_cp_entries]
    build_config = GraalCE.GraalNativeImageConfiguration(
      extra_build_cp=tuple(self._substitutions_cp_entries),
      digests=tuple(build_digests),
      substitution_resources_paths=tuple([
        'org/pantsbuild/zinc/native-image-stubs/substitutions.json',
        # TODO: add this automatically iff the scala version is 2.12!
        # 'org/pantsbuild/zinc/native-image-stubs/substitutions-2.12.json',
      ]),
      reflection_resources_paths=tuple([
        'org/pantsbuild/zinc/native-image-stubs/reflection-config.json',
      ]),
      context=self.context,
    )
    run_digests = [
      ctx.target.sources_snapshot(self.context._scheduler).directory_digest,
    ] + build_digests + [
      graal_rt.directory_digest.directory_digest
    ] + [
      cp.directory_digest.directory_digest
      if isinstance(cp.directory_digest, Snapshot) else cp.directory_digest
      for cp in
      self._capture_dependency_classpath(tuple(dependency_classpath), self.context._scheduler)
    ]
    logger.debug('classes_dir: {}'.format(classes_dir))
    return self._compile_nonhermetic(
      jvm_options, args_with_graal_bootstrap_cp,
      native_image_execution=self.GraalNativeImageExecution(
        build_config=build_config,
        run_digests=tuple(run_digests),
        output_dir=classes_dir,
      ))

  def _compile_nonhermetic(self, jvm_options, scalac_args, **kwargs):
    try:
      result = self.runjava(classpath=self.scalac_bootstrap_classpath_paths(),
                            main=self._scala.compiler_main(),
                            jvm_options=jvm_options,
                            args=scalac_args,
                            workunit_name=self.name(),
                            workunit_labels=[WorkUnitLabel.COMPILER],
                            # NB: Set with self.set_distribution() in __init__!
                            dist=self._dist,
                            **kwargs)
      if isinstance(result, int):
        exit_code = result
      else:
        exit_code = 0
    except ProcessExecutionFailure as e:
      exit_code = e.exit_code

    if exit_code != 0:
      raise self.ScalacCompileError('Scalac compile failed.', exit_code=exit_code)

    return result

  def _compile_hermetic(self, jvm_options, ctx, classes_dir, args, dependency_classpath,
                        scalac_classpath_entries, with_nailgun=False):
    # TODO: fix this -- ClasspathEntry()s should be constructed with a digest, not a snapshot, or
    # the field name should be changed!
    digests = [
      cp.directory_digest.directory_digest for cp in self._scalac_cp_entries
    ] + [
      ctx.target.sources_snapshot(self.context._scheduler).directory_digest,
    ]
    for dep_entry in dependency_classpath:
      if dep_entry.directory_digest:
        digests.append(dep_entry.directory_digest)
      else:
        logger.warning(
          "ClasspathEntry {} didn't have a Digest, so won't be present for hermetic execution"
          .format(dep_entry))

    scalac_classpath_rel = fast_relpath_collection(self.scalac_bootstrap_classpath_paths())

    hermetic_dist = self._hermetic_jvm_distribution()
    jdk_libs_rel, jdk_libs_digest = self._jdk_libs_paths_and_digest(hermetic_dist)
    classpath_rel_jdk = scalac_classpath_rel + jdk_libs_rel

    if with_nailgun:
      raise NotImplementedError('nailgunned hermetic execution is not available for scalac!')
    else:
      argv = ['.jdk/bin/java'] + jvm_options + [
        '-cp', ':'.join(classpath_rel_jdk),
        self._scala.compiler_main(),
      ] + args
      self.context.log.debug('digests: {}'.format(digests))
      merged_input_digest = self.context._scheduler.merge_directories(tuple(
        digests + [jdk_libs_digest]
      ))

    req = ExecuteProcessRequest(
      argv=tuple(argv),
      input_files=merged_input_digest,
      output_directories=(classes_dir,),
      description="scalac compile for {}".format(ctx.target.address.spec),
      jdk_home=text_type(hermetic_dist._underlying._home),
    )

    retry_iteration = 0

    # TODO: any retries will cause workunits to fail!
    while True:
      try:
        res = self.context.execute_process_synchronously_or_raise(req, self.name(), [WorkUnitLabel.COMPILER])
        break
      except ProcessExecutionFailure as e:
        if e.exit_code == 227:
          env = {'_retry_iteration': '{}'.format(retry_iteration)}
          retry_iteration += 1
          req = req.copy(env=env)
          continue
        raise

    # TODO: Materialize as a batch in do_compile or somewhere
    self.context._scheduler.materialize_directories((
      DirectoryToMaterialize(get_buildroot(), res.output_directory_digest),
    ))

    # TODO: This should probably return a ClasspathEntry rather than a Digest
    return res.output_directory_digest

  # NB: lots of methods cribbed from zinc_compile.py -- delete if they error!
  @staticmethod
  def _get_jvm_platform_arguments(settings):
    # TODO: update docstring!
    """Extracts and formats the zinc arguments given in the jvm platform settings.

    This is responsible for the symbol substitution which replaces $JAVA_HOME with the path to an
    appropriate jvm distribution.

    :param settings: The jvm platform settings from which to extract the arguments.
    :type settings: :class:`JvmPlatformSettings`
    """
    jvm_platform_args = []
    if settings.args:
      settings_args = settings.args
      if any('$JAVA_HOME' in a for a in settings.args):
        try:
          distribution = JvmPlatform.preferred_jvm_distribution([settings], strict=True)
        except DistributionLocator.Error:
          distribution = JvmPlatform.preferred_jvm_distribution([settings], strict=False)
        logger.debug('Substituting "$JAVA_HOME" with "{}" in jvm-platform args.'
                     .format(distribution.home))
        settings_args = (a.replace('$JAVA_HOME', distribution.home) for a in settings.args)
      jvm_platform_args.extend(settings_args)
    return jvm_platform_args

  def _scalac_plugin_args(self, scalac_plugin_map, classpath):
    if not scalac_plugin_map:
      return []

    plugin_jar_map = self._find_scalac_plugins(list(scalac_plugin_map.keys()), classpath)
    ret = []
    for name, cp_entries in plugin_jar_map.items():
      # Note that the first element in cp_entries is the one containing the plugin's metadata,
      # meaning that this is the plugin that will be loaded, even if there happen to be other
      # plugins in the list of entries (e.g., because this plugin depends on another plugin).
      ret.append('-Xplugin:{}'.format(':'.join(cp_entries)))
      for arg in scalac_plugin_map[name]:
        ret.append('-P:{}:{}'.format(name, arg))
    return ret

  def _find_scalac_plugins(self, scalac_plugins, classpath):
    """Returns a map from plugin name to list of plugin classpath entries.

    The first entry in each list is the classpath entry containing the plugin metadata.
    The rest are the internal transitive deps of the plugin.

    This allows us to have in-repo plugins with dependencies (unlike javac, scalac doesn't load
    plugins or their deps from the regular classpath, so we have to provide these entries
    separately, in the -Xplugin: flag).

    Note that we don't currently support external plugins with dependencies, as we can't know which
    external classpath elements are required, and we'd have to put the entire external classpath
    on each -Xplugin: flag, which seems excessive.
    Instead, external plugins should be published as "fat jars" (which appears to be the norm,
    since SBT doesn't support plugins with dependencies anyway).
    """
    # Allow multiple flags and also comma-separated values in a single flag.
    plugin_names = {p for val in scalac_plugins for p in val.split(',')}
    if not plugin_names:
      return {}

    active_plugins = {}
    buildroot = get_buildroot()

    cp_product = self.context.products.get_data('runtime_classpath')
    for classpath_element in classpath:
      name = self._maybe_get_plugin_name(classpath_element)
      if name in plugin_names:
        plugin_target_closure = self._plugin_targets('scalac').get(name, [])
        # It's important to use relative paths, as the compiler flags get embedded in the zinc
        # analysis file, and we port those between systems via the artifact cache.
        rel_classpath_elements = [
          os.path.relpath(cpe, buildroot) for cpe in
          ClasspathUtil.internal_classpath(plugin_target_closure, cp_product, self._confs)]
        # If the plugin is external then rel_classpath_elements will be empty, so we take
        # just the external jar itself.
        rel_classpath_elements = rel_classpath_elements or [classpath_element]
        # Some classpath elements may be repeated, so we allow for that here.
        if active_plugins.get(name, rel_classpath_elements) != rel_classpath_elements:
          raise TaskError('Plugin {} defined in {} and in {}'.format(name, active_plugins[name],
                                                                     classpath_element))
        active_plugins[name] = rel_classpath_elements
        if len(active_plugins) == len(plugin_names):
          # We've found all the plugins, so return now to spare us from processing
          # of the rest of the classpath for no reason.
          return active_plugins

    # If we get here we must have unresolved plugins.
    unresolved_plugins = plugin_names - set(active_plugins.keys())
    raise TaskError('Could not find requested plugins: {}'.format(list(unresolved_plugins)))

  @memoized_classmethod
  def _maybe_get_plugin_name(cls, classpath_element):
    """If classpath_element is a scalac plugin, returns its name.

    Returns None otherwise.
    """
    def process_info_file(cp_elem, info_file):
      plugin_info = ElementTree.parse(info_file).getroot()
      if plugin_info.tag != 'plugin':
        raise TaskError('File {} in {} is not a valid scalac plugin descriptor'.format(
            _SCALAC_PLUGIN_INFO_FILE, cp_elem))
      return plugin_info.find('name').text

    if os.path.isdir(classpath_element):
      try:
        with open(os.path.join(classpath_element, _SCALAC_PLUGIN_INFO_FILE), 'r') as plugin_info_file:
          return process_info_file(classpath_element, plugin_info_file)
      except IOError as e:
        if e.errno != errno.ENOENT:
          raise
    else:
      with open_zip(classpath_element, 'r') as jarfile:
        try:
          with closing(jarfile.open(_SCALAC_PLUGIN_INFO_FILE, 'r')) as plugin_info_file:
            return process_info_file(classpath_element, plugin_info_file)
        except KeyError:
          pass
    return None

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
    local_distribution = self._dist
    return self._HermeticDistribution('.jdk', local_distribution)

  @memoized_method
  def _nonhermetic_jvm_distribution(self):
    return JvmPlatform.preferred_jvm_distribution([], strict=True)
