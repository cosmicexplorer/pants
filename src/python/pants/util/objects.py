# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import sys
from abc import abstractmethod
from builtins import object, zip
from collections import OrderedDict, deque, namedtuple

from future.utils import PY2, text_type
from twitter.common.collections import OrderedSet

from pants.util.memo import memoized, memoized_classproperty
from pants.util.meta import AbstractClass


# TODO: add a field for the object's __doc__ string?
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

  def __new__(cls, field_name, type_constraint=None, default_value=None, has_default_value=False):

    # TODO: would we ever want field names to conform to any pattern for any reason?
    # A field name must always be provided, and must be the appropriate text type for the python
    # version.
    if not isinstance(field_name, text_type):
      raise cls.FieldDeclarationError(
        "field_name must be an instance of {!r}, but was instead {!r} (type {!r})."
        .format(text_type, field_name, type(field_name).__name__))

    if type_constraint is None or isinstance(type_constraint, TypeConstraint):
      pass
    else:
      raise cls.FieldDeclarationError(
        "type_constraint for field {field!r} must be an instance of type or TypeConstraint, "
        "but was instead {value!r} (type {the_type!r})."
        .format(field=field_name, value=type_constraint, the_type=type(type_constraint).__name__))

    if not isinstance(has_default_value, bool):
      raise cls.FieldDeclarationError(
        "has_default_value for field {!r} must be a bool, but was instead {!r} (type {!r})."
        .format(field_name, has_default_value, type(has_default_value).__name__))

    # The default value for the field must obey the field's type constraint, if both are
    # provided. This will error at datatype class creation time if not.
    if ((default_value is not None) or has_default_value) and (type_constraint is not None):
      try:
        default_value = type_constraint.validate_satisfied_by(default_value)
      except TypeConstraintError as e:
        raise cls.FieldDeclarationError(
          "default_value {default_value!r} for the field {field_name!r} must satisfy the provided "
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
    type_spec = None
    default_value = None
    has_default_value = False
    type_constraint = None

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
      if isinstance(type_spec, TypeConstraint):
        type_constraint = type_spec
        if type_constraint.has_default_value:
          has_default_value = True
          default_value = type_constraint.default_value
      elif type_spec is None:
        type_constraint = type_spec
      elif isinstance(type_spec, type):
        type_constraint = Exactly(type_spec)
      else:
        raise cls.FieldDeclarationError(
          "type_spec for field {field!r} must be an instance of type or TypeConstraint, if given, "
          "but was instead {value!r} (type {the_type!r})."
          .format(field=field_name, value=type_spec, the_type=type(type_spec).__name__))

    if bool(remaining_decl_elements):
      has_default_value = True
      default_value = remaining_decl_elements.popleft()

    # We were either given an explicit value for `has_default_value`, or we set it depending on
    # whether `default_value` is None.
    if bool(remaining_decl_elements):
      has_default_value = remaining_decl_elements.popleft()
      if bool(remaining_decl_elements):
        raise ValueError(
          "There are too many elements of the tuple {!r} passed to datatype(). "
          "The tuple must have between 1 and 4 arguments. The remaining arguments were: {!r}."
          .format(tuple_decl, list(remaining_decl_elements)))

    return cls(
      field_name=field_name,
      type_constraint=type_constraint,
      default_value=default_value,
      has_default_value=has_default_value)

  @classmethod
  def parse(cls, maybe_decl):
    """The type of `maybe_decl` can be thought of as:

    str | (field_name: str, type?: (TypeConstraint | type), default_value?: Any, has_default_value: bool)

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

  seen_default_value_decl = False
  for maybe_decl in field_decls:
    parsed_decl = DatatypeFieldDecl.parse(maybe_decl)
    # After the first argument with a default value, the rest (rightwards) must each have a default
    # as well.
    if seen_default_value_decl:
      if not parsed_decl.has_default_value:
        raise DatatypeFieldDecl.FieldDeclarationError(
          "datatype field declaration {!r} (parsed into {!r}) must have a default value, "
          "because it follows a declaration with a default value in the field declarations "
          "{!r} (the preceding parsed arguments were: {!r})."
          .format(maybe_decl, parsed_decl, field_decls, parsed_field_list))
    else:
      seen_default_value_decl = parsed_decl.has_default_value
    # namedtuple() already checks field name uniqueness, so we defer to it checking that here.
    parsed_field_list.append(parsed_decl)

  if not superclass_name:
    superclass_name = '_anonymous_namedtuple_subclass'

  field_name_list = [p.field_name for p in parsed_field_list]
  namedtuple_cls = namedtuple(superclass_name, field_name_list, **kwargs)

  # Now we know that the elements of `field_name_list` (the field names) are unique, because the
  # namedtuple() constructor will have ensured that.
  ordered_fields_by_name = OrderedDict((p.field_name, p) for p in parsed_field_list)

  class DataType(namedtuple_cls):
    @classmethod
    def make_type_error(cls, msg, *args, **kwargs):
      return TypeCheckError(cls.__name__, msg, *args, **kwargs)

    @classmethod
    def _parse_args_kwargs(cls, args, kwargs):
      """Assign positional and keyword arguments to the fields of this datatype.

      Apply default values, if a default value was declared for the field and the field was not
      specified in the call to this datatype's constructor.

      TODO: Currently, we are essentially reimplementing the python function argument parsing /
      assignment to positional and keyword params whenever we call a datatype()'s constructor. This
      is unfortunate, potentially slow, and is an artifact of the specific implementation of default
      values in this method.
      """
      # We whittle down the arguments from here, then use the default values (if given) for any
      # remaining ones.
      remaining_field_name_dict = ordered_fields_by_name.copy()

      # Get this from the list of DatatypeFieldDecl above.
      arg_check_error_messages = []

      checked_kwarg_values = {}
      try:
        for field_name in kwargs:
          decl_for_name = remaining_field_name_dict.pop(field_name)
          kwarg_value = kwargs[field_name]

          if decl_for_name.type_constraint is not None:
            try:
              kwarg_value = decl_for_name.type_constraint.validate_satisfied_by(kwarg_value)
            except TypeConstraintError as e:
              arg_check_error_messages.append(
                "field {name!r} was invalid (provided as a keyword argument): {err}"
                .format(name=field_name, err=str(e)))

          checked_kwarg_values[field_name] = kwarg_value
      except KeyError as e:
        raise cls.make_type_error(
          "Unrecognized keyword argument {arg!r} provided to the constructor: "
          "args={args!r},\n"
          "kwargs={kwargs!r}."
          .format(arg=field_name, args=args, kwargs=kwargs),
          e)

      checked_arg_values = []
      try:
        remaining_name_list = list(remaining_field_name_dict.keys())
        if len(remaining_name_list) > 0:
          for name_index in range(0, len(args)):
            name = remaining_name_list[name_index]
            decl_for_name = remaining_field_name_dict.pop(name)
            arg_value = args[name_index]

            if decl_for_name.type_constraint is not None:
              try:
                arg_value = decl_for_name.type_constraint.validate_satisfied_by(arg_value)
              except TypeConstraintError as e:
                arg_check_error_messages.append(
                  "field {name!r} was invalid (provided as positional argument {ind!r}): {err}"
                  .format(name=name, ind=name_index, err=str(e)))

            checked_arg_values.append(arg_value)
      except IndexError as e:
        # If we go out of range, the user has provided too many positional arguments.
        # TODO: this is dead code, because ._replace() itself will raise a TypeError if too many
        # positional arguments are provided!
        raise cls.make_type_error(
          "Too many positional arguments "
          "({n!r} > {num_fields!r}) were provided to the constructor: "
          "args={args!r},\n"
          "kwargs={kwargs!r}. {err}"
          .format(n=len(args), num_fields=len(ordered_fields_by_name), args=args, kwargs=kwargs,
                  err=str(e)),
          e)

      # Collect errors type-checking positional and keyword args while processing, then display them
      # all at once here.
      if arg_check_error_messages:
        raise cls.make_type_error(
          '\n'.join(arg_check_error_messages))

      # If there are any unmentioned fields, get the default value, or let the super(__new__) raise.
      # NB: If None is explicitly provided as the value, the default value will NOT be used!
      all_keyword_args_including_default = checked_kwarg_values.copy()
      if remaining_field_name_dict:
        for field_name, field_decl in remaining_field_name_dict.items():
          if field_decl.has_default_value:
            all_keyword_args_including_default[field_name] = field_decl.default_value

      # Keep all the positional args as positional args, and only add any field defaults by keyword
      # arg.
      return (checked_arg_values, all_keyword_args_including_default)

    def __new__(cls, *args, **kwargs):
      # TODO: Ideally we could execute this exactly once per `cls` but it should be a
      # relatively cheap check.
      if not hasattr(cls.__eq__, '_eq_override_canary'):
        raise cls.make_type_error('Should not override __eq__.')

      # NB: We manually parse `args` and `kwargs` here in order to apply any default values the user
      # may have specified in the call to datatype(), and we need to do that before calling the
      # super constructor, because the super constructor requires every argument to be
      # specified. Some of these values may be changed through coercion if a TypeConstraint does so
      # in its validate_satisfied_by() method. However, unknown keyword args and too many positional
      # args are still handled by the call to the super constructor.
      posn_args, kw_args = cls._parse_args_kwargs(args, kwargs)

      try:
        return super(DataType, cls).__new__(cls, *posn_args, **kw_args)
      except TypeError as e:
        raise cls.make_type_error(str(e), e)

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

    def _replace(_self, **kwds):
      '''Return a new datatype object replacing specified fields with new values'''
      field_dict = _self._asdict()
      field_dict.update(**kwds)
      return type(_self)(**field_dict)

    copy = _replace

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

  default_value = None
  has_default_value = False

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
    """Return `obj` if the object satisfies this type constraint, or raise.

    :raises: `TypeConstraintError` if `obj` does not satisfy the constraint.
    """

    if self.satisfied_by(obj):
      return obj

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
