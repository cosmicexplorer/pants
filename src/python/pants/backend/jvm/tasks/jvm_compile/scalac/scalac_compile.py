# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import errno
import logging
import os
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
from pants.engine.fs import PathGlobs, PathGlobsAndRoot
from pants.java.distribution.distribution import DistributionLocator
from pants.java.jar.jar_dependency import JarDependency
from pants.util.collections import assert_single_element
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

    output_dir = self.execution_strategy_enum.resolve_for_enum_variant({
      self.HERMETIC: '.',
      self.HERMETIC_WITH_NAILGUN: '.',
      self.SUBPROCESS: ctx.classes_dir.path,
      self.NAILGUN: ctx.classes_dir.path,
      # TODO: GRAAL_HERMETIC strategy for remoting!
      self.GRAAL: ctx.classes_dir.path,
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
      '-classpath', ':'.join(user_cp_abs),
      '-d', output_dir,
    ] + trailing_args + ctx.sources

    jvm_options = self._jvm_options

    # NB: For hermetic, we want a relative path.
    classes_dir = fast_relpath(ctx.classes_dir.path, get_buildroot())

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
      self.SUBPROCESS: lambda: self._compile_nonhermetic(jvm_options, scalac_merged_args),
      self.NAILGUN: lambda: self._compile_nonhermetic(jvm_options, scalac_merged_args),
      self.GRAAL: lambda: self._compile_graal_nonhermetic(jvm_options, scalac_merged_args),
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

  @memoized_method
  def _memoized_classpath_entries_with_digests(self, classpath_paths, scheduler):
    snapshots = scheduler.capture_snapshots(tuple(
      PathGlobsAndRoot(PathGlobs([path]), get_buildroot())
      for path in classpath_paths
    ))
    return [ClasspathEntry(path, snapshot) for path, snapshot in list(zip(classpath_paths, snapshots))]

  def _compile_graal_nonhermetic(self, jvm_options, scalac_args):
    bootstrap_classpath_with_graal_runtime = self.scalac_bootstrap_classpath_paths() + [
      self._graal_ce.runtime_jar,
    ]
    args_with_graal_bootstrap_cp = [
      '-Dscala.boot.class.path={}'.format(':'.join(bootstrap_classpath_with_graal_runtime)),
      '-Dscala.usejavacp=true',
    ] + scalac_args
    substitutions_jar_path = assert_single_element(self._substitutions_cp_entries).path
    # TODO: this absoluting needs to be removed to be made remotable!
    absolute_substitutions_jar_path = os.path.join(get_buildroot(), substitutions_jar_path)
    return self._compile_nonhermetic(
      jvm_options, args_with_graal_bootstrap_cp,
      native_image_config=GraalCE.GraalNativeImageConfiguration(
        extra_cp=tuple([absolute_substitutions_jar_path]),
        substitution_resources_paths=tuple([
          'org/pantsbuild/zinc/native-image-stubs/substitutions.json',
          'org/pantsbuild/zinc/native-image-stubs/substitutions-2.12.json',
        ]),
        reflection_resources_paths=tuple([
          'org/pantsbuild/zinc/native-image-stubs/reflection-config.json',
        ]),
        input_fingerprint=self._scalac_classpath_fingerprint,
      ))

  def _compile_nonhermetic(self, jvm_options, scalac_args, **kwargs):
    exit_code = self.runjava(classpath=self.scalac_bootstrap_classpath_paths(),
                             main=self._scala.compiler_main(),
                             jvm_options=jvm_options,
                             args=scalac_args,
                             workunit_name=self.name(),
                             workunit_labels=[WorkUnitLabel.COMPILER],
                             # NB: Set with self.set_distribution() in __init__!
                             dist=self._dist,
                             **kwargs)
    if exit_code != 0:
      raise self.ScalacCompileError('Scalac compile failed.', exit_code=exit_code)

  def _compile_hermetic(self, jvm_options, ctx, classes_dir, zinc_args, dependency_classpath,
                        scalac_classpath_entries, with_nailgun=False):
    raise NotImplementedError('TIME TO DO HERMETIC SCALAC!!!')

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
