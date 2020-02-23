# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
from dataclasses import dataclass
from textwrap import dedent
from typing import (Any, Generator, Generic, Iterable, List, Optional, Tuple, Type, TypeVar, Union,
                    cast)

from pants.util.meta import frozen_after_init
from pants.util.objects import TypeConstraint

# This type variable is used as the `product` field in a `Get`, and represents the type that the
# engine will return from an `await Get[_Product](...)` expression. This type variable is also used
# in the `Tuple[X, ...]` type returned by `await MultiGet(Get[X](...)...)`.
_Product = TypeVar("_Product")
_Params = TypeVar("_Params")


@frozen_after_init
@dataclass(unsafe_hash=True)
class Get(Generic[_Product, _Params]):
    """Experimental synchronous generator API.

    May be called equivalently as either:
    # verbose form: Get[product, subject_declared_type, subject](subject)
    # shorthand form: Get[product, subject_declared_type, subject_declared_type](subject_declared_type(<constructor args for subject>))
    """

    product_type: Type[_Product]
    param_types: Tuple[Type[Any], ...]
    params: 'Params'

    def __repr__(self):
        joined_param_types = ', '.join(t.__name__ for t in self.param_types)
        joined_params = ', '.join(repr(p) for p in self.params)
        return f'Get[{self.product_type.__name__}, [{joined_param_types}]]({joined_params})'

    def __await__(self) -> "Generator[Get[_Product, _Params], None, _Product]":
        """Allow a Get to be `await`ed within an `async` method, returning a strongly-typed result.

        The `yield`ed value `self` is interpreted by the engine within `extern_generator_send()` in
        `native.py`. This class will yield a single Get instance, which is converted into
        `PyGeneratorResponse::Get` from `externs.rs` via the python `cffi` library and the rust
        `cbindgen` crate.

        This is how this method is eventually called:
        - When the engine calls an `async def` method decorated with `@rule`, an instance of
          `types.CoroutineType` is created.
        - The engine will call `.send(None)` on the coroutine, which will either:
          - raise StopIteration with a value (if the coroutine `return`s), or
          - return a `Get` instance to the engine (if the rule instead called `await Get(...)`).
        - The engine will fulfill the `Get` request to produce `x`, then call `.send(x)` and repeat
          the above until StopIteration.

        See more information about implementing this method at
        https://www.python.org/dev/peps/pep-0492/#await-expression.
        """
        result = yield self
        return cast(_Product, result)

    @classmethod
    def _interpret_param_types(
        cls,
        product_type: Type[_Product],
        param_types: Optional[Union[List[Type], Type]] = None,
     ):
        if param_types is None:
            param_types = []
        elif not isinstance(param_types, list):
            param_types = [param_types]

        return dict(
            product_type=product_type,
            param_types=param_types,
        )

    @classmethod
    def __class_getitem__(
        cls,
        product_type: Type[_Product],
        param_types: Optional[Union[List[Type], Type]] = None,
    ):
      """Override the behavior of Get[T] to shuffle over the product T into the constructor args."""
      return lambda *args: cls(*args, **cls._interpret_param_types(product_type, param_types))

    def __init__(
        self,
        params: Optional[Union[List, Any]] = None,
        product_type: Optional[Type[_Product]] = None,
        param_types: Optional[Union[List[Type], Type]] = None,
    ) -> None:        # NB: Compat for Python 3.6, which doesn't recognize the __class_getitem__ override, but *does*
        # contain an __orig_class__ attribute which is gone in later Pythons.
        # TODO: Remove after we drop support for running pants with Python 3.6!
        maybe_orig_class = getattr(self, "__orig_class__", None)
        if maybe_orig_class:
            assert product_type is None
            assert param_types is None
            product_type, param_types = maybe_orig_class.__args__

        assert product_type is not None
        kwargs = self._interpret_param_types(product_type, param_types)

        self.product_type = cast(Type[_Product], kwargs['product_type'])
        self.param_types = tuple(kwargs['param_types'] or ())

        if params is None:
            params = ()
        elif not isinstance(params, (list, tuple)):
            params = (params,)
        self.params = Params(*params)

    @staticmethod
    def extract_constraints(call_node: ast.Call) -> Tuple[str, Tuple[str, ...]]:
        """Parses a `Get(..)` call in one of its two legal forms to return its type constraints.

        :param call_node: An `ast.Call` node representing a call to `Get(..)`.
        :return: A tuple of product type id and subject type id.
        """

        def render_args(args):
            return ", ".join(
                # Dump the Name's id to simplify output when available, falling back to the name of the
                # node's class.
                getattr(a, "id", type(a).__name__)
                for a in args
            )

        # If the Get was provided with a type parameter, use that as the `product_type`.
        func = call_node.func
        subscript_args: Tuple[Any, ...] = ()
        if isinstance(func, ast.Name):
            subscript_args = ()
        elif isinstance(func, ast.Subscript):
            index_expr = func.slice.value # type: ignore[attr-defined]
            if isinstance(index_expr, ast.Name):
                subscript_args = (index_expr,)
            elif isinstance(index_expr, ast.Tuple):
                subscript_args = tuple(index_expr.elts)
            else:
                raise ValueError(f'Unrecognized type arguments T, S... for Get[T, S...]: {ast.dump(index_expr)}')
        else:
            raise ValueError(
                f'Unrecognized Get call node type: expected Get[T] or Get[T, S...], received {ast.dump(call_node)}')

        # Shuffle over the type parameter to be the first argument, if provided.
        if len(subscript_args) == 1:
            product_type, = subscript_args
            return (product_type.id, ())
        elif len(subscript_args) == 2:
            product_type, param_types = subscript_args
            if not isinstance(param_types, (list, tuple)):
                param_types = (param_types,)
            return (product_type.id, tuple(t.id for t in param_types))
        else:
            raise ValueError(f'Invalid Get invocation: expected Get[T] or Get[T, S...], but '
                             f'got: ({render_args(subscript_args)})')

    @classmethod
    def create_statically_for_rule_graph(cls, *args, **kwargs) -> "Get":
        """Construct a `Get` with a None value.

        This method is used to help make it explicit which `Get` instances are parsed from @rule
        bodies and which are instantiated during rule execution.
        """
        return cls(*args, **kwargs)


@frozen_after_init
@dataclass(unsafe_hash=True)
class MultiGet(Generic[_Product, _Params]):
    """Can be constructed with an iterable of `Get()`s and `await`ed to evaluate them in
    parallel."""
    gets: Tuple[Get[_Product, _Params], ...]

    def __await__(self) -> Generator[Tuple[Get[_Product, _Params], ...], None, Tuple[_Product, ...]]:
        """Yield a tuple of Get instances with the same subject/product type pairs all at once.

        The `yield`ed value `self.gets` is interpreted by the engine within `extern_generator_send()` in
        `native.py`. This class will yield a tuple of Get instances, which is converted into
        `PyGeneratorResponse::GetMulti` from `externs.rs`.

        The engine will fulfill these Get instances in parallel, and return a tuple of _Product
        instances to this method, which then returns this tuple to the `@rule` which called
        `await MultiGet(Get[_Product](...) for ... in ...)`.
        """
        result = yield self.gets
        return cast(Tuple[_Product, ...], result)

    def __init__(self, gets: Iterable[Get[_Product, _Params]]) -> None:
        """Create a MultiGet from a generator expression.

        This constructor will infer this class's _Product parameter from the input `gets`.
        """
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

    def __iter__(self):
        return iter(self.params)
