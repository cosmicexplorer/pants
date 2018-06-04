# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod, abstractproperty

from pants.util.meta import AbstractClass, Singleton, classproperty
from pants_test.test_base import TestBase


class AbstractClassTest(TestBase):
  def test_abstract_property(self):
    class AbstractProperty(AbstractClass):
      @abstractproperty
      def property(self):
        pass

    with self.assertRaises(TypeError):
      AbstractProperty()

  def test_abstract_method(self):
    class AbstractMethod(AbstractClass):
      @abstractmethod
      def method(self):
        pass

    with self.assertRaises(TypeError):
      AbstractMethod()


class SingletonTest(TestBase):
  def test_singleton(self):
    class One(Singleton):
      pass

    self.assertIs(One(), One())


class WithProp(object):
  _value = 3

  @classproperty
  def some_property(cls):
    "some docs"
    return cls._value

  @classmethod
  def some_method(cls):
    return cls._value

  @classproperty
  @staticmethod
  def static_property():
    return "static"


class OverridingValueField(WithProp):
  _value = 4


class OverridingValueInit(WithProp):

  def __init__(self, v):
    # This will override the class's _value when evaluating the @classmethod and @classproperty as
    # an instance method/property.
    self._value = v


class OverridingMethodDefSuper(WithProp):

  _other_value = 2

  @classproperty
  def some_property(cls):
    return super(OverridingMethodDefSuper, cls).some_property + cls._other_value


class ClassPropertyTest(TestBase):

  def test_access(self):
    self.assertEqual(3, WithProp.some_property)
    self.assertEqual(3, WithProp().some_property)

    self.assertEqual(3, WithProp.some_method())
    self.assertEqual(3, WithProp().some_method())

    self.assertEqual("static", WithProp.static_property)
    self.assertEqual("static", WithProp().static_property)

  def test_docstring(self):
    self.assertEqual("some docs", WithProp.__dict__['some_property'].__doc__)

  def test_override_value(self):
    self.assertEqual(4, OverridingValueField.some_property)
    self.assertEqual(4, OverridingValueField().some_property)

  def test_override_inst_value(self):
    self.assertEqual(3, OverridingValueInit(3).some_property)
    self.assertEqual(3, OverridingValueInit(3).some_method())

  def test_override_method_super(self):
    self.assertEqual(5, OverridingMethodDefSuper.some_property)
    self.assertEqual(5, OverridingMethodDefSuper().some_property)

  def test_modify_class_value(self):
    class WithFieldToModify(object):
      _z = 44

      @classproperty
      def f(cls):
        return cls._z

    self.assertEqual(44, WithFieldToModify.f)

    # The classproperty reflects the change in state (is not cached by python or something else
    # weird we might do).
    WithFieldToModify._z = 72
    self.assertEqual(72, WithFieldToModify.f)

  def test_has_attr(self):
    self.assertTrue(hasattr(WithProp, 'some_property'))
    self.assertTrue(hasattr(WithProp(), 'some_property'))

  def test_set_attr(self):
    class SetValue(object):
      _x = 3

      @classproperty
      def x_property(cls):
        return cls._x

    self.assertEqual(3, SetValue.x_property)

    # The @classproperty is gone, this is just a regular property now.
    SetValue.x_property = 4
    self.assertEqual(4, SetValue.x_property)
    # The source field is unmodified.
    self.assertEqual(3, SetValue._x)

  def test_delete_attr(self):
    class DeleteValue(object):
      _y = 45

      @classproperty
      def y_property(cls):
        return cls._y

    self.assertEqual(45, DeleteValue.y_property)

    # The @classproperty is gone, but the source field is still alive.
    del DeleteValue.y_property
    self.assertFalse(hasattr(DeleteValue, 'y_property'))
    self.assertTrue(hasattr(DeleteValue, '_y'))
