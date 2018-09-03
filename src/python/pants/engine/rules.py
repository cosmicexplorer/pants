# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast
import functools
import inspect
import logging
from abc import abstractproperty
from builtins import bytes, str
from collections import OrderedDict

from future.utils import PY2
from twitter.common.collections import OrderedSet

from pants.engine.selectors import Get, type_or_constraint_repr
from pants.util.meta import AbstractClass
from pants.util.objects import DatatypeFieldDecl as F
from pants.util.objects import Exactly, convert, datatype


logger = logging.getLogger(__name__)


class _RuleVisitor(ast.NodeVisitor):
  def __init__(self):
    super(_RuleVisitor, self).__init__()
    self.gets = []

  def visit_Call(self, node):
    if not isinstance(node.func, ast.Name) or node.func.id != Get.__name__:
      return
    self.gets.append(Get.extract_constraints(node))


class _GoalProduct(object):
  """GoalProduct is a factory for anonymous singleton types representing the execution of goals.

  The created types are returned by `@console_rule` instances, which may not have any outputs
  of their own.
  """
  PRODUCT_MAP = {}

  @staticmethod
  def _synthesize_goal_product(name):
    product_type_name = '{}GoalExecution'.format(name.capitalize())
    if PY2:
      product_type_name = product_type_name.encode('utf-8')
    return type(product_type_name, (datatype([]),), {})

  @classmethod
  def for_name(cls, name):
    assert isinstance(name, (bytes, str))
    if name is bytes:
      name = name.decode('utf-8')
    if name not in cls.PRODUCT_MAP:
      cls.PRODUCT_MAP[name] = cls._synthesize_goal_product(name)
    return cls.PRODUCT_MAP[name]


def _make_rule(output_type, input_selectors, for_goal=None):
  """A @decorator that declares that a particular static function may be used as a TaskRule.

  :param Constraint output_type: The return/output type for the Rule. This may be either a
    concrete Python type, or an instance of `Exactly` representing a union of multiple types.
  :param list input_selectors: A list of Selector instances that matches the number of arguments
    to the @decorated function.
  :param str for_goal: If this is a @console_rule, which goal string it's called for.
  """

  def wrapper(func):
    if not inspect.isfunction(func):
      raise ValueError('The @rule decorator must be applied innermost of all decorators.')

    caller_frame = inspect.stack()[1][0]
    module_ast = ast.parse(inspect.getsource(func))

    def resolve_type(name):
      resolved = caller_frame.f_globals.get(name) or caller_frame.f_builtins.get(name)
      if not isinstance(resolved, (type, Exactly)):
        # TODO: should this say "...or Exactly instance;"?
        raise ValueError('Expected either a `type` constructor or TypeConstraint instance; '
                         'got: {}'.format(name))
      return resolved

    gets = OrderedSet()
    for node in ast.iter_child_nodes(module_ast):
      if isinstance(node, ast.FunctionDef) and node.name == func.__name__:
        rule_visitor = _RuleVisitor()
        rule_visitor.visit(node)
        gets.update(Get(resolve_type(p), resolve_type(s)) for p, s in rule_visitor.gets)

    # For @console_rule, redefine the function to avoid needing a literal return of the output type.
    if for_goal:
      def goal_and_return(*args, **kwargs):
        res = func(*args, **kwargs)
        if res is not None:
          raise Exception('A @console_rule should not have a return value.')
        return output_type()
      functools.update_wrapper(goal_and_return, func)
      wrapped_func = goal_and_return
    else:
      wrapped_func = func

    wrapped_func._rule = TaskRule(output_type, input_selectors, wrapped_func, input_gets=list(gets))
    wrapped_func.output_type = output_type
    wrapped_func.goal = for_goal

    return wrapped_func
  return wrapper


def rule(output_type, input_selectors):
  return _make_rule(output_type, input_selectors)


def console_rule(goal_name, input_selectors):
  output_type = _GoalProduct.for_name(goal_name)
  return _make_rule(output_type, input_selectors, goal_name)


class Rule(AbstractClass):
  """Rules declare how to produce products for the product graph.

  A rule describes what dependencies must be provided to produce a particular product. They also act
  as factories for constructing the nodes within the graph.
  """

  @abstractproperty
  def output_constraint(self):
    """An output Constraint type for the rule."""

  @abstractproperty
  def input_selectors(self):
    """Collection of input selectors."""


class TaskRule(datatype([
    ('output_constraint', convert(Exactly, should_have_default=False)),
    ('input_selectors', convert(tuple, should_have_default=False)),
    'func',
    ('input_gets', convert_default(tuple)),
]), Rule):
  """A Rule that runs a task function when all of its input selectors are satisfied.

  TODO: Make input_gets non-optional when more/all rules are using them.
  """

  def __new__(cls, func, *args, **kwargs):
    """???"""
    func_name = func.__name__
    try:
      return super(TaskRule, cls).__new__(cls, func=func, *args, **kwargs)
    except TypeError as e:
      raise cls.make_type_error("error in rule `{}`: {}"
                                .format(func_name, str(e)))

  def __str__(self):
    return '({}, {!r}, {})'.format(type_or_constraint_repr(self.output_constraint),
                                   self.input_selectors,
                                   self.func.__name__)


class SingletonRule(datatype([
    ('output_constraint', convert(Exactly, should_have_default=False)),
    'value',
]), Rule):
  """A default rule for a product, which is thus a singleton for that product."""

  @classmethod
  def from_instance(cls, obj):
    return cls(type(obj), obj)

  @property
  def input_selectors(self):
    return tuple()

  def __repr__(self):
    return '{}({}, {})'.format(type(self).__name__, type_or_constraint_repr(self.output_constraint), self.value)


class RootRule(datatype(['output_constraint']), Rule):
  """Represents a root input to an execution of a rule graph.

  Roots act roughly like parameters, in that in some cases the only source of a
  particular type might be when a value is provided as a root subject at the beginning
  of an execution.
  """

  def input_selectors(self):
    return []


class RuleIndex(datatype(['rules', 'roots'])):
  """Holds an index of Tasks and Singletons used to instantiate Nodes."""

  @classmethod
  def create(cls, rule_entries):
    """Creates a RuleIndex with tasks indexed by their output type."""
    # NB make tasks ordered so that gen ordering is deterministic.
    serializable_rules = OrderedDict()
    serializable_roots = set()

    def add_task(product_type, rule):
      if product_type not in serializable_rules:
        serializable_rules[product_type] = OrderedSet()
      serializable_rules[product_type].add(rule)

    def add_rule(rule):
      if isinstance(rule, RootRule):
        serializable_roots.add(rule.output_constraint)
        return
      # TODO: Ensure that interior types work by indexing on the list of types in
      # the constraint. This heterogenity has some confusing implications:
      #   see https://github.com/pantsbuild/pants/issues/4005
      for kind in rule.output_constraint.types:
        add_task(kind, rule)
      add_task(rule.output_constraint, rule)

    for entry in rule_entries:
      if isinstance(entry, Rule):
        add_rule(entry)
      elif hasattr(entry, '__call__'):
        rule = getattr(entry, '_rule', None)
        if rule is None:
          raise TypeError("Expected callable {} to be decorated with @rule.".format(entry))
        add_rule(rule)
      else:
        raise TypeError("Unexpected rule type: {}. "
                        "Rules either extend Rule, or are static functions "
                        "decorated with @rule.".format(type(entry)))

    return cls(serializable_rules, serializable_roots)
