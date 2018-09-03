# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import sys
from abc import abstractmethod
from builtins import object, zip
from collections import Iterable, OrderedDict, deque, namedtuple

from future.utils import PY2, text_type
from twitter.common.collections import OrderedSet

from pants.util.memo import (memoized, memoized_classmethod, memoized_classproperty,
                             memoized_property)
from pants.util.meta import AbstractClass, classproperty


class DatatypeFieldDecl(namedtuple('DatatypeFieldDecl', [
    'field_name',
    'type_constraint',
    'default_value',
    # If the `default_value` is None, setting this argument to True is also required to
    # differentiate from just not providing a `default_value`.
    'has_default_value',
])):
  """Description of a field, used in calls to datatype().

  All elements of the list passed to datatype() are parsed into instances of this class by the
  parse() classmethod.
  """

  class FieldDeclarationError(TypeError): pass

  def __new__(cls, field_name, type_constraint=None, **kwargs):

    # TODO: would we ever want field names to conform to any pattern for any reason?
    # A field name must always be provided, and must be the appropriate text type for the python
    # version.
    if not isinstance(field_name, text_type):
      raise cls.FieldDeclarationError(
        "field_name must be an instance of {!r}, but was instead {!r} (type {!r})."
        .format(text_type, field_name, type(field_name).__name__))

    if 'default_value' in kwargs:
      has_default_value = True
      default_value = kwargs.pop('default_value')
    else:
      has_default_value = False
      default_value = None
    if kwargs:
      raise cls.FieldDeclarationError("Unrecognized keyword arguments: {!r}".format(kwargs))

    if type_constraint is None:
      pass
    elif isinstance(type_constraint, TypeConstraint):
      if not has_default_value and type_constraint.has_default_value:
        has_default_value = True
        default_value = type_constraint.default_value
    elif isinstance(type_constraint, type):
      type_constraint = Exactly(type_constraint)
    else:
      raise cls.FieldDeclarationError(
        "type_constraint for field '{field}' must be an instance of `type` or `TypeConstraint`, "
        "or else None, but was instead {value!r} (type {the_type!r})."
        .format(field=field_name, value=type_constraint, the_type=type(type_constraint).__name__))

    # The default value for the field must obey the field's type constraint, if both are
    # provided. This will error at datatype class creation time if not.
    if has_default_value and (type_constraint is not None):
      try:
        maybe_new_default_value = type_constraint.validate_satisfied_by(default_value)
        if maybe_new_default_value is not None:
          default_value = maybe_new_default_value
      except TypeConstraintError as e:
        raise cls.FieldDeclarationError(
          "default_value {default_value!r} for the field '{field_name}' must satisfy the provided "
          "type_constraint {tc!r}. {err}"
          .format(default_value=default_value,
                  field_name=field_name,
                  tc=type_constraint,
                  err=str(e)),
          e)

    return super(DatatypeFieldDecl, cls).__new__(
      cls, field_name, type_constraint, default_value, has_default_value)

  @classmethod
  def _parse_tuple(cls, tuple_decl):
    """Interpret the elements of a tuple (by position) into a field declaration."""
    # TODO: document what tuples we accept!
    type_spec = None
    type_spec = None

    # NB: We have multiple optional (and some non-optional) positional arguments, so we popleft()
    # things off a deque.
    remaining_decl_elements = deque(tuple_decl)

    if not bool(remaining_decl_elements):
      raise ValueError("Empty tuple {!r} passed to datatype().".format(tuple_decl))

    field_name = text_type(remaining_decl_elements.popleft())

    # A type constraint may optionally be provided, either as a TypeConstraint instance, or as a
    # type, which is shorthand for Exactly(<type>).
    if bool(remaining_decl_elements):
      type_spec = remaining_decl_elements.popleft()

    if bool(remaining_decl_elements):
      raise ValueError(
        "There are too many elements of the tuple {!r} passed to datatype(). "
        "The tuple must have between 1 and 2 elements. The remaining elements were: {!r}."
        .format(tuple_decl, list(remaining_decl_elements)))

    return cls(field_name=field_name, type_constraint=type_spec)

  @classmethod
  def parse(cls, maybe_decl):
    """The type of `maybe_decl` can be thought of as:

    str | DatatypeFieldDecl | (field_name: str, type?: (TypeConstraint | type))

    for convenience.
    """
    if isinstance(maybe_decl, cls):
      # If already a DatatypeFieldDecl instance, just return it.
      parsed_decl = maybe_decl
    elif isinstance(maybe_decl, text_type):
      # A string alone is interpreted as an untyped field of that name.
      parsed_decl = cls(field_name=maybe_decl)
    elif isinstance(maybe_decl, tuple):
      # A tuple may be provided, whose elements are interpreted into a DatatypeFieldDecl.
      parsed_decl = cls._parse_tuple(maybe_decl)
    else:
      # Unrecognized input.
      raise cls.FieldDeclarationError(
        "The field declaration {value!r} must be a {str_type!r}, tuple, "
        "or {this_type!r} instance, but its type was: {the_type!r}."
        .format(value=maybe_decl,
                str_type=text_type,
                this_type=cls.__name__,
                the_type=type(maybe_decl).__name__))

    return parsed_decl


_none_type = type(None)


def _parse_type_constraint(type_constraint):
  if type_constraint is None:
    type_constraint = AnyClass()
  elif isinstance(type_constraint, type):
    type_constraint = Exactly(type_constraint)
  elif not isinstance(type_constraint, TypeConstraint):
    raise TypeError("type_constraint must be a `type`, a `TypeConstraint`, or None: "
                    "was {!r} (type {!r})."
                    .format(type_constraint, type(type_constraint).__name__))

  return type_constraint


def optional(type_constraint=None, allow_default=True):
  """Return a TypeConstraint instance matching `type_constraint`, or the value None."""
  # TODO: do this better? Test this?
  orig_repr = (
    "optional(type_constraint={type_constraint!r}, allow_default={allow_default!r})"
    .format(type_constraint=type_constraint, allow_default=allow_default))

  type_constraint = _parse_type_constraint(type_constraint)
  base_constraint_type = type(type_constraint)
  class ConstraintAlsoAcceptingNone(base_constraint_type):
    has_default_value = True
    default_value = None

    def __init__(self):
      self._types = (_none_type,) + type_constraint._types
      self._desc = type_constraint._desc

    def __repr__(self):
      return orig_repr

    @memoized_classproperty
    def _variance_symbol(cls):
      base = super(ConstraintAlsoAcceptingNone, cls)._variance_symbol
      return '{}?'.format(base)

    def satisfied_by_type(self, obj_type):
      if obj_type is _none_type:
        return True
      return type_constraint.satisfied_by_type(obj_type)

    def satisfied_by(self, obj):
      return (obj is None) or type_constraint.satisfied_by(obj)

    def validate_satisfied_by(self, obj):
      """???"""
      if obj is None:
        return None
      return type_constraint.validate_satisfied_by(obj)

  return ConstraintAlsoAcceptingNone()


def non_empty(type_constraint=None, predicate=bool):
  """???"""
  type_constraint = _parse_type_constraint(type_constraint)
  base_constraint_type = type(type_constraint)
  class ConstraintCheckingEmpty(base_constraint_type):
    has_default_value = False

    @classproperty
    def default_value(cls):
      raise NotImplementedError('???')

    def __init__(self):
      self._types = type_constraint._types
      self._desc = type_constraint._desc

    @memoized_classproperty
    def _variance_symbol(cls):
      base = super(ConstraintCheckingEmpty, cls)._variance_symbol
      return '{}!'.format(base)

    def satisfied_by_type(self, obj_type):
      return type_constraint.satisfied_by_type(obj_type)

    def satisfied_by(self, obj):
      return type_constraint.satisfied_by(obj) and predicate(obj)

    def validate_satisfied_by(self, obj):
      maybe_new_obj = type_constraint.validate_satisfied_by(obj)
      if maybe_new_obj is not None:
        obj = maybe_new_obj

      if not predicate(obj):
        raise TypeConstraintError(
          "value {!r} (with type {!r}) must be True when predicate {} is applied "
          "in this type constraint: {!r}."
          .format(obj, type(obj).__name__, predicate, self))

      return obj

  return ConstraintCheckingEmpty()


def not_none(type_constraint=None):
  """???"""
  return non_empty(type_constraint=type_constraint, predicate=(lambda x: x is not None))


# TODO: when we can restrict the python version to >= 3.6 in our python 3 shard, we can use the
# backported dataclasses library as a backend to take advantage of cool python 3 things like type
# hints (https://github.com/ericvsmith/dataclasses). Python 3.7+ provides dataclasses in the stdlib.
def datatype(field_decls, superclass_name=None, **kwargs):
  """A wrapper for `namedtuple` that accounts for the type of the object in equality.

  Field declarations can be a string, which declares a field with that name and
  no type checking. Field declarations can also be a tuple `('field_name',
  field_type)`, which declares a field named `field_name` which is type-checked
  at construction. If a type is given, the value provided to the constructor for
  that field must be exactly that type (i.e. `type(x) == field_type`), and not
  e.g. a subclass.

  :param field_decls: Iterable of field declarations.
  :return: A type object which can then be subclassed.
  :raises: :class:`TypeError`
  """
  parsed_field_list = []

  default_values = []
  for maybe_decl in field_decls:
    parsed_decl = DatatypeFieldDecl.parse(maybe_decl)
    # After the first argument with a default value, the rest (rightwards) must each have a default
    # as well.
    if default_values:
      if not parsed_decl.has_default_value:
        raise DatatypeFieldDecl.FieldDeclarationError(
          "datatype field declaration {!r} (parsed into {!r}) must have a default value, "
          "because it follows a declaration with a default value in the field declarations "
          "{!r} (the preceding parsed arguments were: {!r})."
          .format(maybe_decl, parsed_decl, field_decls, parsed_field_list))
      else:
        default_values.append(parsed_decl.default_value)
    elif parsed_decl.has_default_value:
      default_values.append(parsed_decl.default_value)
    # namedtuple() already checks field name uniqueness, so we defer to it checking that here.
    parsed_field_list.append(parsed_decl)

  if not superclass_name:
    superclass_name = '_anonymous_namedtuple_subclass'

  field_name_list = [p.field_name for p in parsed_field_list]

  namedtuple_cls = namedtuple(superclass_name, field_name_list, **kwargs)

  if default_values:
    namedtuple_cls.__new__.__defaults__ = tuple(default_values)

  # Now we know that the elements of `field_name_list` (the field names) are unique, because the
  # namedtuple() constructor will have ensured that.
  ordered_fields_by_name = OrderedDict((p.field_name, p) for p in parsed_field_list)

  class DataType(namedtuple_cls):
    @classmethod
    def make_type_error(cls, msg, *args, **kwargs):
      return TypeCheckError(cls.__name__, msg, *args, **kwargs)

    @classmethod
    def _validate_fields(cls, this_object, allow_coercion):
      arg_check_error_messages = []
      updated_value_dict = {}

      for p in parsed_field_list:
        cur_field_constraint = p.type_constraint
        if cur_field_constraint is None:
          continue

        cur_field_name = p.field_name
        cur_field_value = getattr(this_object, cur_field_name)

        try:
          maybe_new_value = cur_field_constraint.validate_satisfied_by(cur_field_value)
          if allow_coercion and (maybe_new_value is not None):
            updated_value_dict[cur_field_name] = maybe_new_value

        except TypeConstraintError as e:
          arg_check_error_messages.append(
            "field '{name}' was invalid: {err}"
            .format(name=cur_field_name, err=str(e)))

      if arg_check_error_messages:
        raise cls.make_type_error('\n'.join(arg_check_error_messages))

      # NB: This relies on the behavior of copy() that when no keyword arguments are provided, it
      # returns the exact original object, which is safe as long as fields are immutable.
      # We also rely on the fact that copy() won't call DataType.__new__() directly, only the
      # supertype's __new__ method, to avoid unbounded mutual recursion.
      return this_object.copy(**updated_value_dict)

    def __new__(cls, *args, **kwargs):
      # TODO: Ideally we could execute this exactly once per `cls` but it should be a
      # relatively cheap check.
      if not hasattr(cls.__eq__, '_eq_override_canary'):
        raise cls.make_type_error('Should not override __eq__.')

      try:
        this_object = super(DataType, cls).__new__(cls, *args, **kwargs)
      except TypeError as e:
        raise cls.make_type_error(str(e), e)

      return cls._validate_fields(this_object, allow_coercion=True)

    def __eq__(self, other):
      if self is other:
        return True

      # Compare types and fields.
      if type(self) != type(other):
        return False
      # Explicitly return super.__eq__'s value in case super returns NotImplemented
      return super(DataType, self).__eq__(other)
    # We define an attribute on the `cls` level definition of `__eq__` that will allow us to detect
    # that it has been overridden.
    __eq__._eq_override_canary = None

    def __ne__(self, other):
      return not (self == other)

    def __hash__(self):
      return super(DataType, self).__hash__()

    # NB: As datatype is not iterable, we need to override both __iter__ and all of the
    # namedtuple methods that expect self to be iterable.
    def __iter__(self):
      raise TypeError("'{}' object is not iterable".format(type(self).__name__))

    def _super_iter(self):
      return super(DataType, self).__iter__()

    def _asdict(self):
      '''Return a new OrderedDict which maps field names to their values'''
      return OrderedDict(zip(self._fields, self._super_iter()))

    @memoized_classproperty
    def _supertype_keyword_only_cached_constructor(cls):
      def ctor(**kw):
        return super(DataType, cls).__new__(cls, **kw)
      return ctor

    def _replace(self, **kwds):
      '''Return a new datatype object replacing specified fields with new values'''
      # TODO: ???/explain
      if not kwds:
        return self

      field_dict = self._asdict()

      arg_check_error_messages = []
      for cur_field_name, cur_field_value in kwds.items():
        try:
          cur_field_decl = ordered_fields_by_name[cur_field_name]
          cur_constraint = cur_field_decl.type_constraint
          if cur_constraint:
            maybe_new_value = cur_constraint.validate_satisfied_by(cur_field_value)
            if maybe_new_value is not None:
              cur_field_value = maybe_new_value

          field_dict[cur_field_name] = cur_field_value
        except KeyError as e:
          arg_check_error_messages.append(
            "Field '{}' was not recognized: {}({})."
            .format(cur_field_name, type(e).__name__, e))
        except TypeConstraintError as e:
          arg_check_error_messages.append(
            "Type checking error for field '{}': {}"
            .format(cur_field_name, str(e)))

      if arg_check_error_messages:
        msg = (
          "Replacing fields {kw!r} of object {obj!r} failed:\n{errs}"
          .format(
            kw=kwds,
            obj=self,
            errs='\n'.join(arg_check_error_messages)))
        raise self.make_type_error(msg)

      return self._supertype_keyword_only_cached_constructor(**field_dict)

    def copy(self, **kwargs):
      """???/made into its own method for better error messages (with the method name in them)"""
      return self._replace(**kwargs)

    # NB: it is *not* recommended to rely on the ordering of the tuple returned by this method.
    def __getnewargs__(self):
      '''Return self as a plain tuple.  Used by copy and pickle.'''
      return tuple(self._super_iter())

    def __repr__(self):
      args_formatted = []
      for field_name in ordered_fields_by_name.keys():
        field_value = getattr(self, field_name)
        args_formatted.append("{}={!r}".format(field_name, field_value))
      return '{class_name}({args_joined})'.format(
        class_name=type(self).__name__,
        args_joined=', '.join(args_formatted))

    def __str__(self):
      elements_formatted = []
      for field_name, decl_for_field in ordered_fields_by_name.items():
        type_constraint_for_field = decl_for_field.type_constraint
        field_value = getattr(self, field_name)
        if not type_constraint_for_field:
          elements_formatted.append(
            # TODO: consider using the repr of arguments in this method.
            "{field_name}={field_value}"
            .format(field_name=field_name,
                    field_value=field_value))
        else:
          elements_formatted.append(
            "{field_name}<{type_constraint}>={field_value}"
            .format(field_name=field_name,
                    type_constraint=decl_for_field.type_constraint,
                    field_value=field_value))
      return '{class_name}({typed_tagged_elements})'.format(
        class_name=type(self).__name__,
        typed_tagged_elements=', '.join(elements_formatted))

  # Return a new type with the given name, inheriting from the DataType class
  # just defined, with an empty class body.
  try:  # Python3
    return type(superclass_name, (DataType,), {})
  except TypeError:  # Python2
    return type(superclass_name.encode('utf-8'), (DataType,), {})


def enum(field_name, all_values):
  """A datatype which can take on a finite set of values. This method is experimental and unstable.

  Any enum subclass can be constructed with its create() classmethod. This method will use the first
  element of `all_values` as the enum value if none is specified.

  :param field_name: A string used as the field for the datatype. Note that enum does not yet
                     support type checking as with datatype.
  :param all_values: An iterable of objects representing all possible values for the enum.
                     NB: `all_values` must be a finite, non-empty iterable with unique values!
  """

  # This call to list() will eagerly evaluate any `all_values` which would otherwise be lazy, such
  # as a generator.
  all_values_realized = list(all_values)
  # `OrderedSet` maintains the order of the input iterable, but is faster to check membership.
  allowed_values_set = OrderedSet(all_values_realized)

  if len(allowed_values_set) < len(all_values_realized):
    raise ValueError("When converting all_values ({}) to a set, at least one duplicate "
                     "was detected. The unique elements of all_values were: {}."
                     .format(all_values_realized, allowed_values_set))

  class ChoiceDatatype(datatype([field_name])):
    allowed_values = allowed_values_set
    default_value = next(iter(allowed_values))

    @memoized_classproperty
    def _singletons(cls):
      """Generate memoized instances of this enum wrapping each of this enum's allowed values."""
      return { value: cls(value) for value in cls.allowed_values }

    @classmethod
    def _check_value(cls, value):
      if value not in cls.allowed_values:
        raise cls.make_type_error(
          "Value {!r} for '{}' must be one of: {!r}."
          .format(value, field_name, cls.allowed_values))

    @classmethod
    def create(cls, value=None):
      # If we get an instance of this enum class, just return it. This means you can call .create()
      # on None, an allowed value for the enum, or an existing instance of the enum.
      if isinstance(value, cls):
        return value

      # Providing an explicit value that is not None will *not* use the default value!
      if value is None:
        value = cls.default_value

      # We actually circumvent the constructor in this method due to the cls._singletons
      # memoized_classproperty, but we want to raise the same error, so we move checking into a
      # common method.
      cls._check_value(value)

      return cls._singletons[value]

    def __new__(cls, *args, **kwargs):
      this_object = super(ChoiceDatatype, cls).__new__(cls, *args, **kwargs)

      field_value = getattr(this_object, field_name)

      cls._check_value(field_value)

      return this_object

    @memoized_classmethod
    def convert_type_constraint(cls, *args, **kwargs):
      return convert(type_spec=Exactly(cls), create_func=cls.create, *args, **kwargs)

  return ChoiceDatatype


class TypedDatatypeClassConstructionError(Exception):

  # TODO: make some wrapper exception class to make this kind of
  # prefixing easy (maybe using a class field format string?).
  def __init__(self, type_name, msg, *args, **kwargs):
    full_msg =  "error: while trying to generate typed datatype {}: {}".format(
      type_name, msg)
    super(TypedDatatypeClassConstructionError, self).__init__(
      full_msg, *args, **kwargs)


class TypedDatatypeInstanceConstructionError(TypeError):

  def __init__(self, type_name, msg, *args, **kwargs):
    full_msg = "error: in constructor of type {}: {}".format(type_name, msg)
    super(TypedDatatypeInstanceConstructionError, self).__init__(
      full_msg, *args, **kwargs)


class TypeCheckError(TypedDatatypeInstanceConstructionError):

  def __init__(self, type_name, msg, *args, **kwargs):
    formatted_msg = "type check error:\n{}".format(msg)
    super(TypeCheckError, self).__init__(
      type_name, formatted_msg, *args, **kwargs)


class TypeConstraintError(TypeError):
  """Indicates a :class:`TypeConstraint` violation."""


class TypeConstraint(AbstractClass):
  """Represents a type constraint.

  Not intended for direct use; instead, use one of :class:`SuperclassesOf`, :class:`Exact` or
  :class:`SubclassesOf`.
  """

  # TODO: ???
  has_default_value = False
  default_value = None

  def __init__(self, *types, **kwargs):
    """Creates a type constraint centered around the given types.

    The type constraint is satisfied as a whole if satisfied for at least one of the given types.

    :param type *types: The focus of this type constraint.
    :param str description: A description for this constraint if the list of types is too long.
    """
    if not types:
      raise ValueError('Must supply at least one type')
    if any(not isinstance(t, type) for t in types):
      raise TypeError('Supplied types must be types. {!r}'.format(types))

    # NB: `types` is converted to tuple here because self.types's docstring says
    # it returns a tuple. Does it matter what type this field is?
    self._types = tuple(types)
    self._desc = kwargs.get('description', None)

  @property
  def types(self):
    """Return the subject types of this type constraint.

    :type: tuple of type
    """
    return self._types

  def satisfied_by(self, obj):
    """Return `True` if the given object satisfies this type constraint.

    :rtype: bool
    """
    return self.satisfied_by_type(type(obj))

  @abstractmethod
  def satisfied_by_type(self, obj_type):
    """Return `True` if the given object satisfies this type constraint.

    :rtype: bool
    """

  def validate_satisfied_by(self, obj):
    """Return `None` if the object satisfies this type constraint, or raise, or return a new object.

    :raises: `TypeConstraintError` if `obj` does not satisfy the constraint.
    """

    if self.satisfied_by(obj):
      return None

    raise TypeConstraintError(
      "value {!r} (with type {!r}) must satisfy this type constraint: {!r}."
      .format(obj, type(obj).__name__, self))

  def __hash__(self):
    return hash((type(self), self._types))

  def __eq__(self, other):
    return type(self) == type(other) and self._types == other._types

  def __ne__(self, other):
    return not (self == other)

  def __str__(self):
    if self._desc:
      constrained_type = '({})'.format(self._desc)
    else:
      if len(self._types) == 1:
        constrained_type = self._types[0].__name__
      else:
        constrained_type = '({})'.format(', '.join(t.__name__ for t in self._types))
    return '{variance_symbol}{constrained_type}'.format(variance_symbol=self._variance_symbol,
                                                        constrained_type=constrained_type)

  def __repr__(self):
    if self._desc:
      constrained_type = self._desc
    else:
      constrained_type = ', '.join(t.__name__ for t in self._types)
    return ('{type_constraint_type}({constrained_type})'
      .format(type_constraint_type=type(self).__name__,
                    constrained_type=constrained_type))


class SuperclassesOf(TypeConstraint):
  """Objects of the exact type as well as any super-types are allowed."""

  _variance_symbol = '-'

  def satisfied_by_type(self, obj_type):
    return any(issubclass(t, obj_type) for t in self._types)


class Exactly(TypeConstraint):
  """Only objects of the exact type are allowed."""

  _variance_symbol = '='

  def satisfied_by_type(self, obj_type):
    return obj_type in self._types

  def graph_str(self):
    if len(self.types) == 1:
      return self.types[0].__name__
    else:
      return repr(self)


class SubclassesOf(TypeConstraint):
  """Objects of the exact type as well as any sub-types are allowed."""

  _variance_symbol = '+'

  def satisfied_by_type(self, obj_type):
    return issubclass(obj_type, self._types)


def convert_default(type_spec, **kwargs):
  """???/makes it easier to do the common python pattern of default=None, then checking for it."""
  assert(isinstance(type_spec, type))

  if 'default_value' in kwargs:
    default_value = kwargs.pop('default_value')
  else:
    default_value = type_spec()

  assume_none_default = kwargs.pop('assume_none_default', True)
  assert(isinstance(assume_none_default, bool))

  if assume_none_default:
    default_value_to_use = None
    def create_func(value=None):
      if value is None:
        return default_value
      return type_spec(value)
  else:
    create_func = type_spec
    default_value_to_use = default_value

  type_constraint_base_class = kwargs.pop('type_constraint_base_class', SubclassesOf)
  assert(issubclass(type_constraint_base_class, TypeConstraint))

  class ConvertDefault(type_constraint_base_class):
    has_default_value = True
    default_value = default_value_to_use

    def __init__(self):
      super(ConvertDefault, self).__init__(type_spec)

    def validate_satisfied_by(self, obj):
      if self.satisfied_by(obj):
        return None
      else:
        return create_func(obj)

  return ConvertDefault()


def convert(type_spec, create_func=None, should_have_default=True):
  """???"""
  if not isinstance(should_have_default, bool):
    raise TypeError('???')

  if type_spec is None:
    raise TypeError('???')
  elif isinstance(type_spec, type):
    if not create_func:
      create_func = type_spec
    type_constraint = SubclassesOf(type_spec)
  elif isinstance(type_spec, Iterable):
    realized_specs = tuple(type_spec)
    for s in realized_specs:
      if not isinstance(s, type):
        raise TypeError('???')
    if not create_func:
      create_func = realized_specs[0]
    type_constraint = SubclassesOf(*realized_specs)
  elif isinstance(type_spec, TypeConstraint):
    if not create_func:
      raise ValueError('???/need a create_func with a TypeConstraint')
    type_constraint = type_spec
  else:
    raise NotImplementedError('???')

  if should_have_default:
    if create_func:
      default_value_to_use = create_func()
    elif type_constraint.has_default_value:
      default_value_to_use = type_constraint.default_value
    else:
      raise ValueError('???/invalid inputs to convert()')

  base_constraint_type = type(type_constraint)
  class Convert(base_constraint_type):
    has_default_value = should_have_default

    if has_default_value:
      default_value = default_value_to_use
    else:
      @classproperty
      def default_value(cls):
        raise NotImplementedError('???')

    @memoized_classproperty
    def _variance_symbol(cls):
      base_sym = super(Convert, cls)._variance_symbol
      return '@{}'.format(base_sym)

    def __init__(self):
      self._types = type_constraint._types
      self._desc = type_constraint._desc

    def satisfied_by_type(self, obj_type):
      return type_constraint.satisfied_by_type(obj_type)

    def satisfied_by(self, obj):
      return type_constraint.satisfied_by(obj)

    def validate_satisfied_by(self, obj):
      if self.satisfied_by(obj):
        # TODO: describe the protocol, and require it or fix it (for validate_satisfied_by())!!!
        return None
      else:
        obj = create_func(obj)

      return obj

  return Convert()


class AnyClass(TypeConstraint):
  _variance_symbol = '*'

  def __init__(self, **kwargs):
    self._types = ()
    self._desc = kwargs.get('description', None)

  def __repr__(self):
    return 'AnyClass()'

  def satisfied_by_type(self, _obj_type):
    return True


class Collection(object):
  """Constructs classes representing collections of objects of a particular type."""
  # TODO: could we check that the input is iterable in the ctor?

  @classmethod
  @memoized
  def of(cls, *element_types):
    union = '|'.join(element_type.__name__ for element_type in element_types)
    type_name = '{}.of({})'.format(cls.__name__, union)
    if PY2:
      type_name = type_name.encode('utf-8')
    # TODO: could we allow type checking in the datatype() invocation here?
    supertypes = (cls, datatype(['dependencies'], superclass_name='Collection'))
    properties = {'element_types': element_types}
    collection_of_type = type(type_name, supertypes, properties)

    # Expose the custom class type at the module level to be pickle compatible.
    setattr(sys.modules[cls.__module__], type_name, collection_of_type)

    return collection_of_type
