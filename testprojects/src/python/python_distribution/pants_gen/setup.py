# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        with_statement)

from distutils.core import Extension
from setuptools import find_packages

from pants_distutils_extensions import setup


c_module = Extension(
  'hello',
  sources=['hello.c'],
  define_macros=[('HELLO_STR', '"hello, world!"')])

setup(
  name='pants_gen_test',
  version='0.0.1',
  ext_modules=[c_module],
  packages=find_packages(),
)
