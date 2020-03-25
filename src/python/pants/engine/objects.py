# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import inspect
import typing
from abc import ABC, abstractmethod
from collections import namedtuple
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Dict, Generic, Iterator, Tuple, TypeVar

from pants.util.memo import memoized_property
from pants.util.meta import decorated_type_checkable, frozen_after_init


class SerializationError(Exception):
    """Indicates an error serializing an object."""


# TODO: Likely no longer necessary, due to the laziness of the product graph.
class Resolvable(ABC):
    """Represents a resolvable object."""

    @property
    @abstractmethod
    def address(self):
        """Return the opaque address descriptor that this resolvable resolves."""

    @abstractmethod
    def resolve(self):
        """Resolve and return the resolvable object."""


def _unpickle_serializable(serializable_class, kwargs):
    # A pickle-compatible top-level function for custom unpickling of Serializables.
    return serializable_class(**kwargs)


# NB: instagram's libCST solves the below!!!

# NB: if we want 100% reproducibly-generated BUILD files (and I think that we do), we likely have to
# enforce some kind of stable ordering for entities to be written out to a BUILD file.
# As mentioned below, not all objects will have a `name` (and therefore not an Address). This goes
# not just for variables and functions within BUILD files, but also sub-expressions of named objects
# (e.g. the individual python_requirement() calls within the `requirements` kwarg of a
# python_requirement_library()).

# (does buildozer not do the above? if not, how does it respond to targets generated via loop or
# function? does it just...not? then what's the point of starlark anyway???)
class Locatable(ABC):
    """Marks a class whose constructor should receive its spec_path relative to the build root.

    Locatable objects will be passed a `spec_path` constructor kwarg that indicates where they were
    parsed. If the object also has a `name` (not all do), then these two fields can be combined into
    an Address.
    """


class SerializablePickle(namedtuple("CustomPickle", ["unpickle_func", "args"])):
    """A named tuple to help the readability of the __reduce__ protocol.

    See: https://docs.python.org/2.7/library/pickle.html#pickling-and-unpickling-extension-types
    """

    @classmethod
    def create(cls, serializable_instance):
        """Return a tuple that implements the __reduce__ pickle protocol for
        serializable_instance."""
        if not Serializable.is_serializable(serializable_instance):
            raise ValueError(
                "Can only create pickles for Serializable objects, given {} of type {}".format(
                    serializable_instance, type(serializable_instance).__name__
                )
            )
        return cls(
            unpickle_func=_unpickle_serializable,
            args=(type(serializable_instance), serializable_instance._asdict()),
        )


class Serializable(ABC):
    """Marks a class that can be serialized into and reconstituted from python builtin values.

    Also provides support for the pickling protocol out of the box.
    """

    @staticmethod
    def is_serializable(obj):
        """Return `True` if the given object conforms to the Serializable protocol.

        :rtype: bool
        """
        if inspect.isclass(obj):
            return Serializable.is_serializable_type(obj)
        return isinstance(obj, Serializable) or hasattr(obj, "_asdict")

    @staticmethod
    def is_serializable_type(type_):
        """Return `True` if the given type's instances conform to the Serializable protocol.

        :rtype: bool
        """
        if not inspect.isclass(type_):
            return Serializable.is_serializable(type_)
        return issubclass(type_, Serializable) or hasattr(type_, "_asdict")

    @abstractmethod
    def _asdict(self):
        """Return a dict mapping this class' properties.

    To meet the contract of a serializable the constructor must accept all the properties returned
    here as constructor parameters; ie the following must be true::

    >>> s = Serializable(...)
    >>> Serializable(**s._asdict()) == s

    Additionally the dict must also contain nothing except Serializables, python primitive values,
    ie: dicts, lists, strings, numbers, bool values, etc or Resolvables that resolve to Serilizables
    or primitive values.

    Any :class:`collections.namedtuple` satisfies the Serializable contract automatically via duck
    typing if it is composed of only primitive python values or Serializable values.
        """

    def __reduce__(self):
        # We implement __reduce__ to steer the pickling process away from __getattr__ scans.  This is
        # both more direct - we know where our instance data lives - and it notably allows __getattr__
        # implementations by Serializable subclasses.  Without the __reduce__, __getattr__ is rendered
        # unworkable since it causes pickle failures.
        # See the note at the bottom of this section:
        # https://docs.python.org/2.7/library/pickle.html#pickling-and-unpickling-normal-class-instances
        return SerializablePickle.create(self)


class SerializableFactory(ABC):
    """Creates :class:`Serializable` objects."""

    @abstractmethod
    def create(self):
        """Return a serializable object.

        :rtype: :class:`Serializable`
        """


class ValidationError(Exception):
    """Indicates invalid fields on an object."""

    def __init__(self, identifier, message):
        """Creates a validation error pertaining to the identified invalid object.

        :param object identifier: Any object whose string representation identifies the invalid object
                                  that led to this validation error.
        :param string message: A message describing the invalid Struct field.
        """
        super().__init__("Failed to validate {id}: {msg}".format(id=identifier, msg=message))


class Validatable(ABC):
    """Marks a class whose instances should validated post-construction."""

    @abstractmethod
    def validate(self):
        """Check that this object's fields are valid.

        :raises: :class:`ValidationError` if this object is invalid.
        """


_C = TypeVar("_C")


class Collection(Generic[_C], Iterable):
    """Constructs classes representing collections of objects of a particular type.

    The produced class will expose its values under a field named dependencies - this is a stable API
    which may be consumed e.g. over FFI from the engine.

    Python consumers of a Collection should prefer to use its standard iteration API.
    """

    def __init__(self, dependencies: typing.Iterable[_C]) -> None:
        self.dependencies = tuple(dependencies)

    def __iter__(self) -> Iterator[_C]:
        return iter(self.dependencies)

    def __bool__(self) -> bool:
        return bool(self.dependencies)


@decorated_type_checkable
def union(cls):
    """A class decorator which other classes can specify that they can resolve to with `UnionRule`.

    Annotating a class with @union allows other classes to use a UnionRule() instance to indicate that
    they can be resolved to this base union class. This class will never be instantiated, and should
    have no members -- it is used as a tag only, and will be replaced with whatever object is passed
    in as the subject of a `await Get(...)`. See the following example:

    @union
    class UnionBase: pass

    @rule
    async def get_some_union_type(x: X) -> B:
      result = await Get(ResultType, UnionBase, x.f())
      # ...

    If there exists a single path from (whatever type the expression `x.f()` returns) -> `ResultType`
    in the rule graph, the engine will retrieve and execute that path to produce a `ResultType` from
    `x.f()`. This requires also that whatever type `x.f()` returns was registered as a union member of
    `UnionBase` with a `UnionRule`.

    Unions allow @rule bodies to be written without knowledge of what types may eventually be provided
    as input -- rather, they let the engine check that there is a valid path to the desired result.
    """
    # TODO: Check that the union base type is used as a tag and nothing else (e.g. no attributes)!
    assert isinstance(cls, type)

    def non_member_error_message(subject):
        if hasattr(cls, "non_member_error_message"):
            return cls.non_member_error_message(subject)
        desc = f' ("{cls.__doc__}")' if cls.__doc__ else ""
        return f"Type {type(subject).__name__} is not a member of the {cls.__name__} @union{desc}"

    return union.define_instance_of(
        cls, non_member_error_message=staticmethod(non_member_error_message)
    )


_K = TypeVar("_K")
_V = TypeVar("_V")


@frozen_after_init
@dataclass(unsafe_hash=True)
class HashableDict(Generic[_K, _V]):
    _tuple_mapping: Tuple[Tuple[_K, _V], ...]

    def __init__(self, mapping: Dict[_K, _V]) -> None:
        self._tuple_mapping = tuple(mapping.items())

    def keys(self) -> Iterable:
        return tuple(entry[0] for entry in self._tuple_mapping)

    def values(self) -> Iterable:
        return tuple(entry[1] for entry in self._tuple_mapping)

    def items(self) -> Tuple[Tuple[_K, _V], ...]:
        return self._tuple_mapping

    @memoized_property
    def as_dict(self) -> Dict[_K, _V]:
        return dict(self._tuple_mapping)
