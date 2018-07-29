# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shlex
from collections import defaultdict
from distutils.command.build_ext import build_ext as distutils_build_ext
from distutils.core import Extension as DistutilsExtension
from setuptools import setup as setuptools_setup

from wheel.install import WheelFile


def _customize_compiler_from_env(compiler):
  cpp_cmd = [os.environ['CPP']] + shlex.split(os.environ['CPPFLAGS'])
  cc_cmd = [os.environ['CC']] + shlex.split(os.environ['CFLAGS'])
  cxx_cmd = [os.environ['CXX']] + shlex.split(os.environ['CXXFLAGS'])
  link_cmd = [os.environ['LDSHARED']] + shlex.split(os.environment['LDFLAGS'])

  compiler.set_executables(
    preprocessor=cpp_cmd,
    compiler=cc_cmd,
    compiler_cxx=cxx_cmd,
    linker_so=link_cmd)


class PantsGenBuildExt(distutils_build_ext):
  """???"""

  def run(self):
    """???/this is from the distutils source!"""
    from distutils.ccompiler import new_compiler

    # 'self.extensions', as supplied by setup.py, is a list of
    # Extension instances.  See the documentation for Extension (in
    # distutils.extension) for details.
    #
    # For backwards compatibility with Distutils 0.8.2 and earlier, we
    # also allow the 'extensions' list to be a list of tuples:
    #    (ext_name, build_info)
    # where build_info is a dictionary containing everything that
    # Extension instances do except the name, with a few things being
    # differently named.  We convert these 2-tuples to Extension
    # instances as needed.

    if not self.extensions:
        return

    # If we were asked to build any C/C++ libraries, make sure that the
    # directory where we put them is in the library search path for
    # linking extensions.
    if self.distribution.has_c_libraries():
        build_clib = self.get_finalized_command('build_clib')
        self.libraries.extend(build_clib.get_library_names() or [])
        self.library_dirs.append(build_clib.build_clib)

    # Setup the CCompiler object that we'll use to do all the
    # compiling and linking
    self.compiler = new_compiler(compiler=self.compiler,
                                 verbose=self.verbose,
                                 dry_run=self.dry_run,
                                 force=self.force)

    self.compiler = _customize_compiler_from_env(self.compiler)
    # If we are cross-compiling, init the compiler now (if we are not
    # cross-compiling, init would not hurt, but people may rely on
    # late initialization of compiler even if they shouldn't...)
    if os.name == 'nt' and self.plat_name != get_platform():
        self.compiler.initialize(self.plat_name)

    # And make sure that any compile/link-related options (which might
    # come from the command-line or from the setup script) are set in
    # that CCompiler object -- that way, they automatically apply to
    # all compiling and linking done here.
    if self.include_dirs is not None:
      for inc_dir in self.include_dirs:
        self.compiler.add_include_dir(inc_dir)
    if self.define is not None:
        # 'define' option is a list of (name,value) tuples
        for (name, value) in self.define:
            self.compiler.define_macro(name, value)
    if self.undef is not None:
        for macro in self.undef:
            self.compiler.undefine_macro(macro)
    if self.libraries is not None:
      for lib_name in self.libraries:
        self.compiler.add_library(lib_name)
    if self.library_dirs is not None:
      for lib_dir in self.library_dirs:
        self.compiler.add_library_dir(lib_dir)
    if self.rpath is not None:
      for rpath_dir in self.rpath:
        self.compiler.add_runtime_library_dir(rpath_dir)
    if self.link_objects is not None:
        self.compiler.set_link_objects(self.link_objects)

    # Now actually compile and link everything.
    self.build_extensions()


def setup(cmdclass=None, **kwargs):
  cmdclass = cmdclass or {}
  cmdclass.update({
    'build_ext': PantsGenBuildExt,
  })
  setuptools_setup(**kwargs)
