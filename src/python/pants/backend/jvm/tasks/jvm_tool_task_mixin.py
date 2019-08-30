# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.base.build_environment import get_buildroot
from pants.task.task import TaskBase
from pants.util.dirutil import fast_relpath_collection
from pants.util.memo import memoized_method


class JvmToolTaskMixin(JvmToolMixin, TaskBase):
  """A JvmToolMixin specialized for mixing in to Tasks.

  Tasks that mix this in are those that run code in a JVM as an implementation detail of
  their operation. Examples are compile.java, checkstyle etc.  This is distinct from tasks
  whose explicit purpose is to run code in a JVM, such as test.junit or jvm.run.  Those
  tasks extend `pants.backend.jvm.tasks.JvmTask`.

  Note that this mixin is typically used by extending `pants.backend.jvm.tasks.NailgunTask`
  rather than being mixed in directly.

  :API: public
  """

  @classmethod
  def prepare(cls, options, round_manager):
    super().prepare(options, round_manager)
    cls.prepare_tools(round_manager)

  def tool_jar(self, key, scope=None):
    """Get the jar for the tool previously registered under key in the given scope.

    See tool_jar_entry
    """
    return self.tool_jar_from_products(self.context.products, key, scope=self._scope(scope))

  def tool_jar_entry(self, key, scope=None):
    """Get a ClasspathEntry for the jar for the tool previously registered under key in the given scope.

    :param string key: The key the tool configuration was registered under.
    :param string scope: The scope the tool configuration was registered under; the task scope by
                         default.
    :returns: A single jar path.
    :rtype: string
    :raises: `JvmToolMixin.InvalidToolClasspath` when the tool classpath is not composed of exactly
             one jar.
    """
    return self.tool_jar_entry_from_products(self.context.products, key, scope=self._scope(scope))

  def tool_classpath(self, key, scope=None):
    """Get a classpath for the tool previously registered under key in the given scope.

    See tool_classpath_entry.
    """
    return self.tool_classpath_from_products(self.context.products, key, scope=self._scope(scope))

  def tool_classpath_entries(self, key, scope=None):
    """Get ClasspathEntries for the tool previously registered under key in the given scope.

    :API: public

    :param string key: The key the tool configuration was registered under.
    :param string scope: The scope the tool configuration was registered under; the task scope by
                         default.
    :returns: A list of paths.
    :rtype: list
    """
    return self.tool_classpath_entries_from_products(self.context.products, key, scope=self._scope(scope))

  def _scope(self, scope=None):
    return scope or self.options_scope

  @memoized_method
  def tool_classpath_snapshot(self, key, scope=None):
    """???"""
    cp_abs_paths = self.tool_classpath(key, scope=scope)
    cp_rel_paths = fast_relpath_collection(cp_abs_paths, get_buildroot())
    return self.digest_classpath_paths_synchronously(
      tuple(cp_rel_paths), get_buildroot(), self.context._scheduler)
