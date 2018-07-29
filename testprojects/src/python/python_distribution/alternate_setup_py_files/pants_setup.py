# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        with_statement)

from setuptools import setup, find_packages
from distutils.core import Extension


c_module = Extension('hello', sources=['hello.c'])

setup(
  name='alternate_setup_py_files',
  version='0.0.1',
  ext_modules=[c_module],
  packages=find_packages(),
)
