# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import pickle

from pants_test.base_test import BaseTest
from pants.util.objects import (
  datatype, typed_datatype, TypedDatatypeClassConstructionError,
  TypedDatatypeInstanceConstructionError, TypeCheckError)


class ExportedDatatype(datatype('ExportedDatatype', ['val'])):
  pass


class AbsClass(object):
  pass


class SomeTypedDatatype(typed_datatype('SomeTypedDatatype', {'my_val': int})):
  pass


class AnotherTypedDatatype(typed_datatype(str('AnotherTypedDatatype'), {
    'a_field': str,
    'better_field': list,
})):
  pass


class UnicodeNamedTypedDatatype(typed_datatype(
    unicode('UnicodeNamedTypedDatatype'), {
      'nothing_special': str,
      'just_another_arg': int,
    }
)):
  pass


class ReturnsNotImplemented(object):
  def __eq__(self, other):
    return NotImplemented


class DatatypeTest(BaseTest):

  def test_eq_with_not_implemented_super(self):
    class DatatypeSuperNotImpl(datatype('Foo', ['val']), ReturnsNotImplemented, tuple):
      pass

    self.assertNotEqual(DatatypeSuperNotImpl(1), DatatypeSuperNotImpl(1))

  def test_type_included_in_eq(self):
    foo = datatype('Foo', ['val'])
    bar = datatype('Bar', ['val'])

    self.assertFalse(foo(1) == bar(1))
    self.assertTrue(foo(1) != bar(1))

  def test_subclasses_not_equal(self):
    foo = datatype('Foo', ['val'])
    class Bar(foo):
      pass

    self.assertFalse(foo(1) == Bar(1))
    self.assertTrue(foo(1) != Bar(1))

  def test_repr(self):
    bar = datatype('Bar', ['val', 'zal'])
    self.assertEqual('Bar(val=1, zal=1)', repr(bar(1, 1)))

    class Foo(datatype('F', ['val']), AbsClass):
      pass

    # Maybe this should be 'Foo(val=1)'?
    self.assertEqual('F(val=1)', repr(Foo(1)))

  def test_not_iterable(self):
    bar = datatype('Bar', ['val'])
    with self.assertRaises(TypeError):
      for x in bar(1):
        pass

  def test_deep_copy(self):
    # deep copy calls into __getnewargs__, which namedtuple defines as implicitly using __iter__.

    bar = datatype('Bar', ['val'])

    self.assertEqual(bar(1), copy.deepcopy(bar(1)))

  def test_atrs(self):
    bar = datatype('Bar', ['val'])
    self.assertEqual(1, bar(1).val)

  def test_as_dict(self):
    bar = datatype('Bar', ['val'])

    self.assertEqual({'val': 1}, bar(1)._asdict())

  def test_replace_non_iterable(self):
    bar = datatype('Bar', ['val', 'zal'])

    self.assertEqual(bar(1, 3), bar(1, 2)._replace(zal=3))

  def test_properties_not_assignable(self):
    bar = datatype('Bar', ['val'])
    bar_inst = bar(1)
    with self.assertRaises(AttributeError):
      bar_inst.val = 2

  def test_invalid_field_name(self):
    with self.assertRaises(ValueError):
      datatype('Bar', ['0isntanallowedfirstchar'])

  def test_subclass_pickleable(self):
    before = ExportedDatatype(1)
    dumps = pickle.dumps(before, protocol=2)
    after = pickle.loads(dumps)
    self.assertEqual(before, after)

  def test_mixed_argument_types(self):
    bar = datatype('Bar', ['val', 'zal'])
    self.assertEqual(bar(1, 2), bar(val=1, zal=2))
    self.assertEqual(bar(1, 2), bar(zal=2, val=1))

  def test_double_passed_arg(self):
    bar = datatype('Bar', ['val', 'zal'])
    with self.assertRaises(TypeError):
      bar(1, val=1)

  def test_too_many_args(self):
    bar = datatype('Bar', ['val', 'zal'])
    with self.assertRaises(TypeError):
      bar(1, 1, 1)

  def test_unexpect_kwarg(self):
    bar = datatype('Bar', ['val'])
    with self.assertRaises(TypeError):
      bar(other=1)


class TypedDatatypeTest(BaseTest):

  def test_class_construction(self):
    # NB: typed_datatype subclasses declared at top level are the success cases
    # here by not failing on import.

    with self.assertRaises(TypedDatatypeClassConstructionError):
      class NonStrType(typed_datatype(3, {'a': int})): pass

    # This raises a TypeError because it doesn't provide a required argument.
    with self.assertRaises(TypeError):
      class NoFields(typed_datatype('NoFields')): pass

    with self.assertRaises(TypedDatatypeClassConstructionError):
      class NonDictFields(typed_datatype('NonDictFields', [
          ('field', 'value'),
      ])): pass

    with self.assertRaises(TypedDatatypeClassConstructionError):
      class NonTypeFields(typed_datatype('NonTypeFields', {'a': 3})): pass

  def test_instance_construction(self):

    # no positional args
    with self.assertRaises(TypeError):
      SomeTypedDatatype('hey')

    # not providing all the fields
    try:
      SomeTypedDatatype()
      self.fail("should have errored: not providing all constructor fields")
    except TypedDatatypeInstanceConstructionError as e:
      self.assertIn('my_val', str(e))

    with self.assertRaises(TypedDatatypeInstanceConstructionError):
      AnotherTypedDatatype(a_field='a')

    # unrecognized fields
    try:
      SomeTypedDatatype(not_a_val=3)
      self.fail("should have an unrecognized field error")
    except TypedDatatypeInstanceConstructionError as e:
      self.assertIn('not_a_val', str(e))

    # type checking failures
    with self.assertRaises(TypeCheckError):
      SomeTypedDatatype(my_val='not a number')

    try:
      AnotherTypedDatatype(
        a_field=3,
        better_field=3)
      self.fail("should have had a type check error")
    except TypeCheckError as e:
      self.assertIn('a_field', str(e))
      self.assertIn('better_field', str(e))
