# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.codegen.thrift.java.java_thrift_library import \
    JavaThriftLibrary


class CustomScroogeJavaThriftLibrary(JavaThriftLibrary):

  default_sources_globs = '*.thrift'

  def __init__(self, *args, **kwargs):
    kwargs['fatal_warnings'] = False
    super(CustomScroogeJavaThriftLibrary, self).__init__(*args, **kwargs)

  @classmethod
  def alias(cls):
    return 'custom_scrooge_java_thrift_library'
