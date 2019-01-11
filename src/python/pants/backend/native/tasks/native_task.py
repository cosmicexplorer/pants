# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import filter

from pants.backend.native.config.environment import CppToolchain, CToolchain
from pants.backend.native.subsystems.native_build_settings import NativeBuildSettings
from pants.backend.native.subsystems.native_toolchain import (NativeToolchain,
                                                              ToolchainVariantRequest)
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.native.targets.packaged_native_library import PackagedNativeLibrary
from pants.build_graph.dependency_context import DependencyContext
from pants.task.task import Task
from pants.util.collections import assert_single_element
from pants.util.memo import memoized_classproperty, memoized_method, memoized_property
from pants.util.meta import classproperty
from pants.util.objects import Exactly, SubclassesOf


class NativeTask(Task):

  @classproperty
  def source_target_constraint(cls):
    """Return a type constraint which is evaluated to determine "source" targets for this task.

    This is used to make it clearer which tasks act on which targets, since the compile and link
    tasks work on different target sets (just C and just C++ in the compile tasks, and both in the
    link task).

    :return: :class:`pants.util.objects.TypeConstraint`
    """
    raise NotImplementedError()

  @memoized_classproperty
  def dependent_target_constraint(cls):
    """Return a type contraint which is evaluated to determine dependencies for a target.

    This is used to make strict_deps() calculation automatic and declarative.

    :return: :class:`pants.util.objects.TypeConstraint`
    """
    return SubclassesOf(NativeLibrary)

  @memoized_classproperty
  def external_dependent_constraint(cls):
    """???"""
    return Exactly(PackagedNativeLibrary)

  @classmethod
  def subsystem_dependencies(cls):
    return super(NativeTask, cls).subsystem_dependencies() + (
      # We use a globally-scoped dependency on NativeBuildSettings because the toolchain and
      # dependency calculation need to be the same for both compile and link tasks (and subscoping
      # would break that).
      NativeBuildSettings,
      NativeToolchain.scoped(cls),
    )

  @classmethod
  def prepare(cls, options, round_manager):
    super(NativeTask, cls).prepare(options, round_manager)
    # Allow the deferred_sources_mapping to take place first
    round_manager.optional_data('deferred_sources')

  @classmethod
  def implementation_version(cls):
    return super(NativeTask, cls).implementation_version() + [('NativeTask', 0)]

  @memoized_property
  def _native_build_settings(self):
    return NativeBuildSettings.global_instance()

  @memoized_property
  def _native_toolchain(self):
    return NativeToolchain.scoped_instance(self)

  @memoized_property
  def _toolchain_variant_request(self):
    return ToolchainVariantRequest(
      toolchain=self._native_toolchain,
      variant=self._native_build_settings.toolchain_variant)

  @memoized_method
  def get_c_toolchain_variant(self):
    return self._request_single(CToolchain, self._toolchain_variant_request)

  @memoized_method
  def get_cpp_toolchain_variant(self):
    return self._request_single(CppToolchain, self._toolchain_variant_request)

  @memoized_method
  def native_deps(self, target):
    return self.strict_deps_for_target(
      target, predicate=self.dependent_target_constraint.satisfied_by)

  @memoized_method
  def packaged_native_deps(self, target):
    return self.strict_deps_for_target(
      target, predicate=self.external_dependent_constraint.satisfied_by)

  def strict_deps_for_target(self, target, predicate=None):
    """Get the dependencies of `target` filtered by `predicate`, accounting for 'strict_deps'.

    If 'strict_deps' is on, instead of using the transitive closure of dependencies, targets will
    only be able to see their immediate dependencies declared in the BUILD file. The 'strict_deps'
    setting is obtained from the result of `get_compile_settings()`.

    NB: This includes the current target in the result.
    """
    if self._native_build_settings.get_strict_deps_value_for_target(target):
      strict_deps = target.strict_dependencies(DependencyContext())
      if predicate:
        filtered_deps = list(filter(predicate, strict_deps))
      else:
        filtered_deps = strict_deps
      deps = [target] + filtered_deps
    else:
      deps = self.context.build_graph.transitive_subgraph_of_addresses(
        [target.address], predicate=predicate)

    # Filter out the beginning target depending on whether it matches the predicate.
    # TODO: There should be a cleaner way to do this.
    deps = filter(predicate, deps)

    return deps

  def _add_product_at_target_base(self, product_mapping, target, value):
    product_mapping.add(target, target.target_base).append(value)

  def _retrieve_single_product_at_target_base(self, product_mapping, target):
    self.context.log.debug("product_mapping: {}".format(product_mapping))
    self.context.log.debug("target: {}".format(target))
    product = product_mapping.get(target)
    single_base_dir = assert_single_element(product.keys())
    single_product = assert_single_element(product[single_base_dir])
    return single_product

  # TODO(#5869): delete this when we can request Subsystems from options in tasks!
  def _request_single(self, product, subject):
    # NB: This is not supposed to be exposed to Tasks yet -- see #4769 to track the status of
    # exposing v2 products in v1 tasks.
    return self.context._scheduler.product_request(product, [subject])[0]
