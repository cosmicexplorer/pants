# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from distutils.core import Extension
from setuptools import setup, find_packages

# from pantssetup import find_external_modules

setup(
  name='fasthello_test',
  version='1.0.0',
  # TODO: make this pull a new type of target called python_native_extension
  # (with a subpackage path and (native) sources), which can
  # then be added to deps. also make a new target called python_module which is
  # just a python_library, but with a subpackage path so pants knows how to
  # generate the setup.py. python_distribution could then be a complete
  # alternative to provides=setup_py(...) (???)
  # ext_modules=find_external_modules(),
  ext_modules=[Extension(str('super_greet'), [str('super_greet.cpp')])],
  packages=find_packages(),
  install_requires=['pycountry==17.1.2']
)
