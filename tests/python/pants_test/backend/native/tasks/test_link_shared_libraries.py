# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.backend.native.tasks.cpp_compile import CppCompile
from pants.backend.native.tasks.link_shared_libraries import LinkSharedLibraries
from pants.backend.native.tasks.native_external_library_fetch import NativeExternalLibraryFetch
from pants_test.backend.native.tasks.native_task_test_base import NativeTaskTestBase


class LinkSharedLibrariesTest(NativeTaskTestBase):
  @classmethod
  def task_type(cls):
    return LinkSharedLibraries

  def test_caching(self):
    cpp = self. create_simple_cpp_library(ctypes_native_library=NativeArtifact(lib_name='test'),)

    native_elf_fetch_task_type = self.synthesize_task_subtype(NativeExternalLibraryFetch,
                                                              'native_elf_fetch_scope')
    cpp_compile_task_type = self.synthesize_task_subtype(CppCompile, 'cpp_compile_scope')
    context = self.context(target_roots=[cpp],
                           for_task_types=[native_elf_fetch_task_type, cpp_compile_task_type])

    native_elf_fetch = native_elf_fetch_task_type(context,
                                                  os.path.join(self.pants_workdir,
                                                               'native_elf_fetch'))
    native_elf_fetch.execute()

    cpp_compile = cpp_compile_task_type(context, os.path.join(self.pants_workdir, 'cpp_compile'))
    cpp_compile.execute()

    link_shared_libraries = self.create_task(context)
    link_shared_libraries.execute()
    link_shared_libraries.execute()
