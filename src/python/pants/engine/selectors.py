# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Generator, Generic, Iterable, Optional, Tuple, Type, TypeVar, cast

from pants.util.meta import frozen_after_init
from pants.util.objects import TypeConstraint


_Product = TypeVar("_Product")


@frozen_after_init
@dataclass(unsafe_hash=True)
class Get(Generic[_Product]):
  """Experimental synchronous generator API.

  May be called equivalently as either:
    # verbose form: Get(product_type, subject_declared_type, subject)
    # shorthand form: Get(product_type, subject_type(subject))
  """
  product: Type[_Product]
  subject_declared_type: type
  subject: Optional[Any]

  def __await__(self) -> 'Generator[Any, Any, _Product]':
    """Allow a Get to be `await`ed, returning a type-checked result."""
    result = yield self
    return cast(_Product, result)

  @classmethod
  def __class_getitem__(cls, product_type):
    return lambda *args: cls(product_type, *args)

  def __init__(self, *args: Any) -> None:
    if len(args) not in (2, 3):
      raise ValueError(
        f'Expected either two or three arguments to {Get.__name__}; got {args}.'
      )
    if len(args) == 2:
      product, subject = args

      if isinstance(subject, (type, TypeConstraint)):
        raise TypeError(dedent("""\
          The two-argument form of Get does not accept a type as its second argument.

          args were: Get({args!r})

          Get.create_statically_for_rule_graph() should be used to generate a Get() for
          the `input_gets` field of a rule. If you are using a `yield Get(...)` in a rule
          and a type was intended, use the 3-argument version:
          Get({product!r}, {subject_type!r}, {subject!r})
          """.format(args=args, product=product, subject_type=type(subject), subject=subject)
        ))

      subject_declared_type = type(subject)
    else:
      product, subject_declared_type, subject = args

    self.product = product
    self.subject_declared_type = subject_declared_type
    self.subject = subject

  @staticmethod
  def extract_constraints(call_node):
    """Parses a `Get(..)` call in one of its two legal forms to return its type constraints.

    :param call_node: An `ast.Call` node representing a call to `Get(..)`.
    :return: A tuple of product type id and subject type id.
    """
    def render_args(args):
      return ', '.join(
        # Dump the Name's id to simplify output when available, falling back to the name of the
        # node's class.
        getattr(a, 'id', type(a).__name__)
        for a in args)

    # If the Get was provided with a type parameter, use that as the `product_type`.
    func = call_node.func
    if isinstance(func, ast.Name):
      subscript_args = ()
    elif isinstance(func, ast.Subscript):
      index_expr = func.slice.value
      if isinstance(index_expr, ast.Name):
        subscript_args = (index_expr,)
      else:
        raise ValueError(f'Unrecognized Get type index arg: {index_expr}')
    else:
      raise ValueError(f'Unrecognized Get call node type: {func}')

    combined_args = subscript_args + tuple(call_node.args)

    if len(combined_args) == 2:
      product_type, subject_constructor = combined_args
      if not isinstance(product_type, ast.Name) or not isinstance(subject_constructor, ast.Call):
        # TODO(#7114): describe what types of objects are expected in the get call, not just the
        # argument names. After #7114 this will be easier because they will just be types!
        raise ValueError(
          'Two arg form of {} expected (product_type, subject_type(subject)), but '
                        'got: ({})'.format(Get.__name__, render_args(combined_args)))
      return (product_type.id, subject_constructor.func.id)
    elif len(combined_args) == 3:
      product_type, subject_declared_type, _ = combined_args
      if not isinstance(product_type, ast.Name) or not isinstance(subject_declared_type, ast.Name):
        raise ValueError(
          'Three arg form of {} expected (product_type, subject_declared_type, subject), but '
                        'got: ({})'.format(Get.__name__, render_args(combined_args)))
      return (product_type.id, subject_declared_type.id)
    else:
      raise ValueError('Invalid {}; expected either two or three args, but '
                      'got: ({})'.format(Get.__name__, render_args(combined_args)))

  @classmethod
  def create_statically_for_rule_graph(cls, product_type, subject_type):
    """Construct a `Get` with a None value.

    This method is used to help make it explicit which `Get` instances are parsed from @rule bodies
    and which are instantiated during rule execution.
    """
    return cls(product_type, subject_type, None)


@frozen_after_init
@dataclass(unsafe_hash=True)
class MultiGet(Generic[_Product]):
  """Can be constructed with an iterable of `Get()`s and `await`ed to evaluate them in parallel."""
  gets: Tuple[Get[_Product], ...]

  def __await__(self) -> Generator[Any, Any, Tuple[_Product, ...]]:
    result = yield self.gets
    return cast(Tuple[_Product, ...], result)

  def __init__(self, gets: Iterable[Get[_Product]]) -> None:
    self.gets = tuple(gets)


@frozen_after_init
@dataclass(unsafe_hash=True)
class Params:
  """A set of values with distinct types.

  Distinct types are enforced at consumption time by the rust type of the same name.
  """
  params: Tuple[Any, ...]

  def __init__(self, *args: Any) -> None:
    self.params = tuple(args)
