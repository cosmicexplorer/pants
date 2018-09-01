# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import pickle
import re
from abc import abstractmethod
from builtins import object, str

from future.utils import PY2, PY3, text_type

from pants.util.objects import Convert
from pants.util.objects import DatatypeFieldDecl as F
from pants.util.objects import (Exactly, SubclassesOf, SuperclassesOf, TypeCheckError,
                                TypedDatatypeInstanceConstructionError, datatype, enum, optional)
from pants_test.base_test import BaseTest


class TypeConstraintTestBase(BaseTest):
  class A(object):
    pass

  class B(A):
    pass

  class C(B):
    pass

  class BPrime(A):
    pass


class SuperclassesOfTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaises(ValueError):
      SubclassesOf()

  def test_single(self):
    superclasses_of_b = SuperclassesOf(self.B)
    self.assertEqual((self.B,), superclasses_of_b.types)
    self.assertTrue(superclasses_of_b.satisfied_by(self.A()))
    self.assertTrue(superclasses_of_b.satisfied_by(self.B()))
    self.assertFalse(superclasses_of_b.satisfied_by(self.BPrime()))
    self.assertFalse(superclasses_of_b.satisfied_by(self.C()))

  def test_multiple(self):
    superclasses_of_a_or_b = SuperclassesOf(self.A, self.B)
    self.assertEqual((self.A, self.B), superclasses_of_a_or_b.types)
    self.assertTrue(superclasses_of_a_or_b.satisfied_by(self.A()))
    self.assertTrue(superclasses_of_a_or_b.satisfied_by(self.B()))
    self.assertFalse(superclasses_of_a_or_b.satisfied_by(self.BPrime()))
    self.assertFalse(superclasses_of_a_or_b.satisfied_by(self.C()))


class ExactlyTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaises(ValueError):
      Exactly()

  def test_single(self):
    exactly_b = Exactly(self.B)
    self.assertEqual((self.B,), exactly_b.types)
    self.assertFalse(exactly_b.satisfied_by(self.A()))
    self.assertTrue(exactly_b.satisfied_by(self.B()))
    self.assertFalse(exactly_b.satisfied_by(self.BPrime()))
    self.assertFalse(exactly_b.satisfied_by(self.C()))

  def test_multiple(self):
    exactly_a_or_b = Exactly(self.A, self.B)
    self.assertEqual((self.A, self.B), exactly_a_or_b.types)
    self.assertTrue(exactly_a_or_b.satisfied_by(self.A()))
    self.assertTrue(exactly_a_or_b.satisfied_by(self.B()))
    self.assertFalse(exactly_a_or_b.satisfied_by(self.BPrime()))
    self.assertFalse(exactly_a_or_b.satisfied_by(self.C()))

  def test_disallows_unsplatted_lists(self):
    with self.assertRaises(TypeError):
      Exactly([1])

  def test_str_and_repr(self):
    exactly_b_types = Exactly(self.B, description='B types')
    self.assertEqual("=(B types)", str(exactly_b_types))
    self.assertEqual("Exactly(B types)", repr(exactly_b_types))

    exactly_b = Exactly(self.B)
    self.assertEqual("=B", str(exactly_b))
    self.assertEqual("Exactly(B)", repr(exactly_b))

    exactly_multiple = Exactly(self.A, self.B)
    self.assertEqual("=(A, B)", str(exactly_multiple))
    self.assertEqual("Exactly(A, B)", repr(exactly_multiple))

  def test_checking_via_bare_type(self):
    self.assertTrue(Exactly(self.B).satisfied_by_type(self.B))
    self.assertFalse(Exactly(self.B).satisfied_by_type(self.C))


class SubclassesOfTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaises(ValueError):
      SubclassesOf()

  def test_single(self):
    subclasses_of_b = SubclassesOf(self.B)
    self.assertEqual((self.B,), subclasses_of_b.types)
    self.assertFalse(subclasses_of_b.satisfied_by(self.A()))
    self.assertTrue(subclasses_of_b.satisfied_by(self.B()))
    self.assertFalse(subclasses_of_b.satisfied_by(self.BPrime()))
    self.assertTrue(subclasses_of_b.satisfied_by(self.C()))

  def test_multiple(self):
    subclasses_of_b_or_c = SubclassesOf(self.B, self.C)
    self.assertEqual((self.B, self.C), subclasses_of_b_or_c.types)
    self.assertTrue(subclasses_of_b_or_c.satisfied_by(self.B()))
    self.assertTrue(subclasses_of_b_or_c.satisfied_by(self.C()))
    self.assertFalse(subclasses_of_b_or_c.satisfied_by(self.BPrime()))
    self.assertFalse(subclasses_of_b_or_c.satisfied_by(self.A()))


class ExportedDatatype(datatype(['val'])):
  pass


class AbsClass(object):
  pass


class SomeTypedDatatype(datatype([('val', int)])): pass


class SomeMixin(object):

  @abstractmethod
  def as_str(self): pass

  def stripped(self):
    return self.as_str().strip()


class TypedWithMixin(datatype([('val', text_type)]), SomeMixin):
  """Example of using `datatype()` with a mixin."""

  def as_str(self):
    return self.val


class AnotherTypedDatatype(datatype([('string', text_type), ('elements', list)])): pass


class WithExplicitTypeConstraint(datatype([('a_string', text_type), ('an_int', Exactly(int))])): pass


class MixedTyping(datatype(['value', ('name', text_type)])): pass


class WithDefaultValueTuple(datatype([('an_int', int, 3)])): pass


# `F` is what we imported `pants.util.objects.DatatypeFieldDecl` as.
class WithJustDefaultValueExplicitFieldDecl(datatype([F('a_bool', Exactly(bool), True)])): pass


class WithDefaultValueNumericExplicitFieldDecl(datatype([F('a_tuple', Convert(tuple))])): pass


class WithDefaultValueNoneExplicitFieldDecl(datatype([F('a_bool', Convert(bool))])): pass


class SomeBaseClass(object):
  @abstractmethod
  def something(self): pass


class SomeDatatypeClass(SomeBaseClass):
  def something(self):
    return 'asdf'

  def __repr__(self):
    return 'SomeDatatypeClass()'


class WithSubclassTypeConstraint(datatype([('some_value', SubclassesOf(SomeBaseClass))])): pass


class NonNegativeInt(datatype([('an_int', int)])):
  """Example of overriding __new__() to perform deeper argument checking."""

  # NB: __new__() in the class returned by datatype() will raise if any kwargs are provided, but
  # subclasses are free to pass around kwargs as long as they don't forward them to that particular
  # __new__() method.
  def __new__(cls, *args, **kwargs):
    # Call the superclass ctor first to ensure the type is correct.
    this_object = super(NonNegativeInt, cls).__new__(cls, *args, **kwargs)

    value = this_object.an_int

    if value < 0:
      raise cls.make_type_error("value is negative: {!r}.".format(value))

    return this_object


class CamelCaseWrapper(datatype([('nonneg_int', NonNegativeInt)])): pass


class ReturnsNotImplemented(object):
  def __eq__(self, other):
    return NotImplemented


class SomeEnum(enum('x', [1, 2])): pass


class DatatypeTest(BaseTest):

  def test_eq_with_not_implemented_super(self):
    class DatatypeSuperNotImpl(datatype(['val']), ReturnsNotImplemented, tuple):
      pass

    self.assertNotEqual(DatatypeSuperNotImpl(1), DatatypeSuperNotImpl(1))

  def test_type_included_in_eq(self):
    foo = datatype(['val'])
    bar = datatype(['val'])

    self.assertFalse(foo(1) == bar(1))
    self.assertTrue(foo(1) != bar(1))

  def test_subclasses_not_equal(self):
    foo = datatype(['val'])
    class Bar(foo):
      pass

    self.assertFalse(foo(1) == Bar(1))
    self.assertTrue(foo(1) != Bar(1))

  def test_repr(self):
    bar = datatype(['val', 'zal'], superclass_name='Bar')
    self.assertEqual('Bar(val=1, zal=1)', repr(bar(1, 1)))

    class Foo(datatype(['val'], superclass_name='F'), AbsClass):
      pass

    self.assertEqual('Foo(val=1)', repr(Foo(1)))

  def test_not_iterable(self):
    bar = datatype(['val'])
    with self.assertRaises(TypeError):
      for x in bar(1):
        pass

  def test_deep_copy(self):
    # deep copy calls into __getnewargs__, which namedtuple defines as implicitly using __iter__.

    bar = datatype(['val'])

    self.assertEqual(bar(1), copy.deepcopy(bar(1)))

  def test_atrs(self):
    bar = datatype(['val'])
    self.assertEqual(1, bar(1).val)

  def test_as_dict(self):
    bar = datatype(['val'])

    self.assertEqual({'val': 1}, bar(1)._asdict())

  def test_replace_non_iterable(self):
    bar = datatype(['val', 'zal'])

    self.assertEqual(bar(1, 3), bar(1, 2)._replace(zal=3))

  def test_properties_not_assignable(self):
    bar = datatype(['val'])
    bar_inst = bar(1)
    with self.assertRaises(AttributeError):
      bar_inst.val = 2

  def test_invalid_field_name(self):
    with self.assertRaises(ValueError):
      datatype(['0isntanallowedfirstchar'])

  def test_override_eq_disallowed(self):
    class OverridesEq(datatype(['myval'])):
      def __eq__(self, other):
        return other.myval == self.myval
    with self.assertRaises(TypeCheckError) as tce:
      OverridesEq(1)
    self.assertIn('Should not override __eq__.', str(tce.exception))

  def test_subclass_pickleable(self):
    before = ExportedDatatype(1)
    dumps = pickle.dumps(before, protocol=2)
    after = pickle.loads(dumps)
    self.assertEqual(before, after)

  def test_mixed_argument_types(self):
    bar = datatype(['val', 'zal'])
    self.assertEqual(bar(1, 2), bar(val=1, zal=2))
    self.assertEqual(bar(1, 2), bar(zal=2, val=1))

  def test_double_passed_arg(self):
    bar = datatype(['val', 'zal'])
    with self.assertRaises(TypeError):
      bar(1, val=1)

  def test_too_many_args(self):
    bar = datatype(['val', 'zal'])
    with self.assertRaises(TypeError):
      bar(1, 1, 1)

  def test_unexpect_kwarg(self):
    bar = datatype(['val'])
    with self.assertRaises(TypeError):
      bar(other=1)


class TypedDatatypeTest(BaseTest):

  def test_class_construction_errors(self):
    # NB: datatype subclasses declared at top level are the success cases
    # here by not failing on import.

    # If the type_name can't be converted into a suitable identifier, throw a
    # ValueError.
    with self.assertRaises(F.FieldDeclarationError) as cm:
      class NonStrType(datatype([int])): pass
    expected_msg = (
      "The field declaration <type 'int'> must be a <type 'unicode'>, tuple, or 'DatatypeFieldDecl' instance, but its type was: 'type'.")
    self.assertIn(expected_msg, str(cm.exception))

    with self.assertRaises(TypeError) as cm:
      class NoFields(datatype()): pass
    expected_msg = (
      "datatype() missing 1 required positional argument: 'field_decls'"
      if PY3 else
      "datatype() takes at least 1 argument (0 given)"
    )
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(F.FieldDeclarationError) as cm:
      class JustTypeField(datatype([text_type])): pass
    expected_msg = (
      "The field declaration <type 'unicode'> must be a <type 'unicode'>, tuple, or 'DatatypeFieldDecl' instance, but its type was: 'type'.")
    self.assertIn(str(cm.exception), expected_msg)

    with self.assertRaises(F.FieldDeclarationError) as cm:
      class NonStringField(datatype([3])): pass
    expected_msg = (
      "The field declaration 3 must be a <type 'unicode'>, tuple, or 'DatatypeFieldDecl' instance, but its type was: 'int'.")
    self.assertIn(str(cm.exception), expected_msg)

    with self.assertRaises(ValueError) as cm:
      class NonStringTypeField(datatype([(32, int)])): pass
    expected_msg = (
      "Type names and field names must be valid identifiers: '32'"
      if PY3 else
      "Type names and field names cannot start with a number: '32'"
    )
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(ValueError) as cm:
      class MultipleSameName(datatype([
          'field_a',
          'field_b',
          'field_a',
      ])):
        pass
    expected_msg = "Encountered duplicate field name: 'field_a'"
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(ValueError) as cm:
      class MultipleSameNameWithType(datatype([
            'field_a',
            ('field_a', int),
          ])):
        pass
    expected_msg = "Encountered duplicate field name: 'field_a'"
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(F.FieldDeclarationError) as cm:
      class InvalidTypeSpec(datatype([('a_field', 2)])): pass
    expected_msg = (
      "type_spec for field u'a_field' must be an instance of type or TypeConstraint, if given, but was instead 2 (type 'int').")
    self.assertIn(str(cm.exception), expected_msg)

  def test_class_construction_default_value(self):
    with self.assertRaises(ValueError) as cm:
      class WithEmptyTuple(datatype([()])): pass

    with self.assertRaises(F.FieldDeclarationError) as cm:
      class WithInvalidTypeDefaultValue(datatype([('x', int, None)])): pass
    expected_msg = (
      "default_value None for the field {}'x' "
      "must satisfy the provided type_constraint Exactly(int)."
      .format('u' if PY2 else ''))
    self.assertIn(expected_msg, str(cm.exception))

    # Check that even if `has_default_value` is True, the default value is still checked against the
    # `type_constraint` at datatype() call time.
    with self.assertRaises(F.FieldDeclarationError) as cm:
      class WithInvalidTypeDefaultAndRawArg(datatype([('x', int, None, True)])): pass
    expected_msg = (
      "default_value None for the field {}'x' "
      "must satisfy the provided type_constraint Exactly(int)."
      .format('u' if PY2 else ''))
    self.assertIn(expected_msg, str(cm.exception))

    # This could just be a tuple, but the keyword in the F constructor adds clarity. This works
    # because of the expanded type constraint.
    class WithCheckedDefaultValue(datatype([
        F('x', Exactly(int, type(None)), None, has_default_value=True)]
    )): pass
    self.assertEqual(WithCheckedDefaultValue().x, None)
    self.assertEqual(WithCheckedDefaultValue(3).x, 3)
    self.assertEqual(WithCheckedDefaultValue(x=3).x, 3)

    with self.assertRaises(ValueError):
      class WithTooManyElementsTuple(datatype([('x', int, None, True, None)])): pass

    with self.assertRaises(TypeError):
      class WithTooManyKwargsTuple(datatype([
          F('x', int, None, True, has_default_value=False)
      ])): pass

  def test_instance_construction_default_value(self):
    self.assertEqual(WithDefaultValueTuple().an_int, 3)
    self.assertEqual(WithDefaultValueTuple(4).an_int, 4)
    self.assertEqual(WithDefaultValueTuple(an_int=4).an_int, 4)

  def test_instance_construction_by_repr(self):
    some_val = SomeTypedDatatype(3)
    self.assertEqual(3, some_val.val)
    self.assertEqual(repr(some_val), "SomeTypedDatatype(val=3)")
    self.assertEqual(str(some_val), "SomeTypedDatatype(val<=int>=3)")

    some_object = WithExplicitTypeConstraint(text_type('asdf'), 45)
    self.assertEqual(some_object.a_string, 'asdf')
    self.assertEqual(some_object.an_int, 45)
    def compare_repr(include_unicode = False):
      expected_message = "WithExplicitTypeConstraint(a_string={unicode_literal}'asdf', an_int=45)"\
        .format(unicode_literal='u' if include_unicode else '')
      self.assertEqual(repr(some_object), expected_message)
    def compare_str(unicode_type_name):
      expected_message = "WithExplicitTypeConstraint(a_string<={}>=asdf, an_int<=int>=45)".format(unicode_type_name)
      self.assertEqual(str(some_object), expected_message)
    if PY2:
      compare_str('unicode')
      compare_repr(include_unicode=True)
    else:
      compare_str('str')
      compare_repr()

    some_nonneg_int = NonNegativeInt(an_int=3)
    self.assertEqual(3, some_nonneg_int.an_int)
    self.assertEqual(repr(some_nonneg_int), "NonNegativeInt(an_int=3)")
    self.assertEqual(str(some_nonneg_int), "NonNegativeInt(an_int<=int>=3)")

    wrapped_nonneg_int = CamelCaseWrapper(NonNegativeInt(45))
    # test attribute naming for camel-cased types
    self.assertEqual(45, wrapped_nonneg_int.nonneg_int.an_int)
    # test that repr() is called inside repr(), and str() inside str()
    self.assertEqual(repr(wrapped_nonneg_int),
                     "CamelCaseWrapper(nonneg_int=NonNegativeInt(an_int=45))")
    self.assertEqual(
      str(wrapped_nonneg_int),
      "CamelCaseWrapper(nonneg_int<=NonNegativeInt>=NonNegativeInt(an_int<=int>=45))")

    mixed_type_obj = MixedTyping(value=3, name=text_type('asdf'))
    self.assertEqual(3, mixed_type_obj.value)
    def compare_repr(include_unicode = False):
      expected_message = "MixedTyping(value=3, name={unicode_literal}'asdf')" \
        .format(unicode_literal='u' if include_unicode else '')
      self.assertEqual(repr(mixed_type_obj), expected_message)
    def compare_str(unicode_type_name):
      expected_message = "MixedTyping(value=3, name<={}>=asdf)".format(unicode_type_name)
      self.assertEqual(str(mixed_type_obj), expected_message)
    if PY2:
      compare_str('unicode')
      compare_repr(include_unicode=True)
    else:
      compare_str('str')
      compare_repr()

    subclass_constraint_obj = WithSubclassTypeConstraint(SomeDatatypeClass())
    self.assertEqual('asdf', subclass_constraint_obj.some_value.something())
    self.assertEqual(repr(subclass_constraint_obj),
                     "WithSubclassTypeConstraint(some_value=SomeDatatypeClass())")
    self.assertEqual(
      str(subclass_constraint_obj),
      "WithSubclassTypeConstraint(some_value<+SomeBaseClass>=SomeDatatypeClass())")

  def test_mixin_type_construction(self):
    obj_with_mixin = TypedWithMixin(text_type(' asdf '))
    def compare_repr(include_unicode = False):
      expected_message = "TypedWithMixin(val={unicode_literal}' asdf ')" \
        .format(unicode_literal='u' if include_unicode else '')
      self.assertEqual(repr(obj_with_mixin), expected_message)
    def compare_str(unicode_type_name):
      expected_message = "TypedWithMixin(val<={}>= asdf )".format(unicode_type_name)
      self.assertEqual(str(obj_with_mixin), expected_message)
    if PY2:
      compare_str('unicode')
      compare_repr(include_unicode=True)
    else:
      compare_str('str')
      compare_repr()
    self.assertEqual(obj_with_mixin.as_str(), ' asdf ')
    self.assertEqual(obj_with_mixin.stripped(), 'asdf')

  def test_instance_construction_errors(self):
    with self.assertRaises(TypeError) as cm:
      SomeTypedDatatype(something=3)
    # self.assertEqual(str(ex_base), "KeyError('something',)")
    expected_msg = "error: in constructor of type SomeTypedDatatype: type check error:\\nUnrecognized keyword argument \'something\' provided to the constructor: args=(),\\nkwargs={\'something\': 3}."
    ex_str = str(cm.exception)
    self.assertIn(KeyError.__name__, ex_str)
    self.assertIn(expected_msg, ex_str)

    # not providing all the fields
    with self.assertRaises(TypeError) as cm:
      SomeTypedDatatype()
    expected_msg_ending = (
      "__new__() missing 1 required positional argument: 'val'"
      if PY3 else
      "__new__() takes exactly 2 arguments (1 given)"
    )
    expected_msg = "error: in constructor of type SomeTypedDatatype: type check error:\\n"
    ex_str = str(cm.exception)
    self.assertIn(TypeError.__name__, ex_str)
    self.assertIn(expected_msg, ex_str)
    self.assertIn(expected_msg_ending, ex_str)

    # unrecognized fields
    with self.assertRaises(TypeError) as cm:
      SomeTypedDatatype(3, 4)
    expected_msg = """error: in constructor of type SomeTypedDatatype: type check error:\\nToo many positional arguments (2 > 1) were provided to the constructor: args=(3, 4),\\nkwargs={}. list index out of range"""
    ex_str = str(cm.exception)
    self.assertIn(IndexError.__name__, ex_str)
    self.assertIn(expected_msg, ex_str)

    with self.assertRaises(TypedDatatypeInstanceConstructionError) as cm:
      CamelCaseWrapper(nonneg_int=3)
    expected_msg = (
      """error: in constructor of type CamelCaseWrapper: type check error:
field 'nonneg_int' was invalid (provided as a keyword argument): value 3 (with type 'int') must satisfy this type constraint: Exactly(NonNegativeInt).""")
    self.assertEqual(expected_msg, str(cm.exception))

    # test that too many positional args fails
    with self.assertRaises(TypeError) as cm:
      CamelCaseWrapper(4, 5)
    expected_msg = """error: in constructor of type CamelCaseWrapper: type check error:\\nToo many positional arguments (2 > 1) were provided to the constructor: args=(4, 5),\\nkwargs={}. list index out of range"""
    ex_str = str(cm.exception)
    self.assertIn(IndexError.__name__, ex_str)
    self.assertIn(expected_msg, ex_str)

    # test that kwargs with keywords that aren't field names fail the same way
    with self.assertRaises(TypeError) as cm:
      CamelCaseWrapper(4, a=3)
    expected_msg = "error: in constructor of type CamelCaseWrapper: type check error:\\nUnrecognized keyword argument \'a\' provided to the constructor: args=(4,),\\nkwargs={\'a\': 3}."
    ex_str = str(cm.exception)
    self.assertIn(KeyError.__name__, ex_str)
    self.assertIn(expected_msg, ex_str)

  def test_type_check_errors(self):
    # single type checking failure
    with self.assertRaises(TypeError) as cm:
      SomeTypedDatatype([])
    def compare_str(include_unicode=False):
      expected_message = (
        """error: in constructor of type SomeTypedDatatype: type check error:
field {unicode_literal}'val' was invalid (provided as positional argument 0): value [] (with type 'list') must satisfy this type constraint: Exactly(int)."""
      .format(unicode_literal='u' if include_unicode else ''))
      self.assertEqual(str(cm.exception), expected_message)
    if PY2:
      compare_str(include_unicode=True)
    else:
      compare_str()

    # type checking failure with multiple arguments (one is correct)
    with self.assertRaises(TypeCheckError) as cm:
      AnotherTypedDatatype(text_type('correct'), text_type('should be list'))
    def compare_str(unicode_type_name, include_unicode=False):
      expected_message = (
        """error: in constructor of type AnotherTypedDatatype: type check error:
field {unicode_literal}'elements' was invalid (provided as positional argument 1): value {unicode_literal}'should be list' (with type '{type_name}') must satisfy this type constraint: Exactly(list)."""
      .format(type_name=unicode_type_name, unicode_literal='u' if include_unicode else ''))
      self.assertEqual(str(cm.exception), expected_message)
    if PY2:
      compare_str('unicode', include_unicode=True)
    else:
      compare_str('str')

    # type checking failure on both arguments
    with self.assertRaises(TypeCheckError) as cm:
      AnotherTypedDatatype(3, text_type('should be list'))
    def compare_str(unicode_type_name, include_unicode=False):
      expected_message = (
        """error: in constructor of type AnotherTypedDatatype: type check error:
field {unicode_literal}'string' was invalid (provided as positional argument 0): value 3 (with type 'int') must satisfy this type constraint: Exactly({type_name}).
field {unicode_literal}'elements' was invalid (provided as positional argument 1): value {unicode_literal}'should be list' (with type '{type_name}') must satisfy this type constraint: Exactly(list)."""
          .format(type_name=unicode_type_name, unicode_literal='u' if include_unicode else ''))
      self.assertEqual(str(cm.exception), expected_message)
    if PY2:
      compare_str('unicode', include_unicode=True)
    else:
      compare_str('str')

    with self.assertRaises(TypeCheckError) as cm:
      NonNegativeInt(text_type('asdf'))
    def compare_str(unicode_type_name, include_unicode=False):
      expected_message = (
        """error: in constructor of type NonNegativeInt: type check error:
field {unicode_literal}'an_int' was invalid (provided as positional argument 0): value {unicode_literal}'asdf' (with type '{type_name}') must satisfy this type constraint: Exactly(int)."""
          .format(type_name=unicode_type_name, unicode_literal='u' if include_unicode else ''))
      self.assertEqual(str(cm.exception), expected_message)
    if PY2:
      compare_str('unicode', include_unicode=True)
    else:
      compare_str('str')

    with self.assertRaises(TypeCheckError) as cm:
      NonNegativeInt(-3)
    expected_msg = (
      """error: in constructor of type NonNegativeInt: type check error:
value is negative: -3.""")
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(TypeCheckError) as cm:
      WithSubclassTypeConstraint(3)
    def compare_str(include_unicode=False):
      expected_message = (
        """error: in constructor of type WithSubclassTypeConstraint: type check error:
field {unicode_literal}'some_value' was invalid (provided as positional argument 0): value 3 (with type 'int') must satisfy this type constraint: SubclassesOf(SomeBaseClass)."""
          .format(unicode_literal='u' if include_unicode else ''))
      self.assertEqual(str(cm.exception), expected_message)
    if PY2:
      compare_str(include_unicode=True)
    else:
      compare_str()

  def test_copy(self):
    obj = AnotherTypedDatatype(string='some_string', elements=[1, 2, 3])
    new_obj = obj.copy(string='another_string')

    self.assertEqual(type(obj), type(new_obj))
    self.assertEqual(new_obj.string, 'another_string')
    self.assertEqual(new_obj.elements, obj.elements)

  def test_copy_failure(self):
    obj = AnotherTypedDatatype(string='some string', elements=[1,2,3])

    with self.assertRaises(TypeCheckError) as cm:
      obj.copy(nonexistent_field=3)
    expected_msg = (
      "error: in constructor of type AnotherTypedDatatype: type check error:\\nUnrecognized keyword argument \'nonexistent_field\' provided to the constructor")
    self.assertIn(expected_msg, str(cm.exception))

    with self.assertRaises(TypeError) as cm:
      obj.copy(3, 4)

    with self.assertRaises(TypeCheckError) as cm:
      obj.copy(elements=3)
    expected_msg = (
      """error: in constructor of type AnotherTypedDatatype: type check error:
field 'elements' was invalid (provided as a keyword argument): value 3 (with type 'int') must satisfy this type constraint: Exactly(list).""")
    self.assertEqual(str(cm.exception), expected_msg)

  def test_enum_class_creation_errors(self):
    expected_rx = re.escape(
      "When converting all_values ([1, 2, 3, 1]) to a set, at least one duplicate "
      "was detected. The unique elements of all_values were: OrderedSet([1, 2, 3]).")
    with self.assertRaisesRegexp(ValueError, expected_rx):
      class DuplicateAllowedValues(enum('x', [1, 2, 3, 1])): pass

  def test_enum_instance_creation(self):
    self.assertEqual(1, SomeEnum.create().x)
    self.assertEqual(2, SomeEnum.create(2).x)
    self.assertEqual(1, SomeEnum(1).x)
    self.assertEqual(2, SomeEnum(x=2).x)

  def test_enum_instance_creation_errors(self):
    expected_rx = re.escape(
      "Value 3 for 'x' must be one of: OrderedSet([1, 2]).")
    with self.assertRaisesRegexp(TypeCheckError, expected_rx):
      SomeEnum.create(3)
    with self.assertRaisesRegexp(TypeCheckError, expected_rx):
      SomeEnum(3)
    with self.assertRaisesRegexp(TypeCheckError, expected_rx):
      SomeEnum(x=3)

    expected_rx_falsy_value = re.escape(
      "Value {}'' for 'x' must be one of: OrderedSet([1, 2])."
      .format('u' if PY2 else ''))
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_falsy_value):
      SomeEnum(x='')

  def test_optional(self):
    class OptionalAny(datatype([('x', optional(), None)])): pass
    self.assertTrue(OptionalAny().x is None)
    self.assertTrue(OptionalAny(None).x is None)
    self.assertEqual(OptionalAny(3).x, 3)


    class OptionalTyped(datatype([('x', optional(int), None)])): pass
    self.assertTrue(OptionalTyped().x is None)
    self.assertEqual(OptionalTyped(3).x, 3)
    with self.assertRaises(TypeCheckError):
      OptionalTyped('asdf')

    class OptionalExplicitConstraint(datatype([
        ('x', optional(Exactly(int, text_type)), None),
    ])): pass
    self.assertTrue(OptionalExplicitConstraint().x is None)
    self.assertEqual(OptionalExplicitConstraint(3).x, 3)
    self.assertEqual(OptionalExplicitConstraint('asdf').x, 'asdf')
    with self.assertRaises(TypeCheckError):
      OptionalExplicitConstraint(True)

    class OptionalNonNoneDefault(datatype([('x', optional(int), 3)])): pass
    self.assertEqual(OptionalNonNoneDefault().x, 3)
    self.assertTrue(OptionalNonNoneDefault(None).x is None)
    self.assertEqual(OptionalNonNoneDefault(4).x, 4)
    with self.assertRaises(TypeCheckError):
      OptionalNonNoneDefault(True)
