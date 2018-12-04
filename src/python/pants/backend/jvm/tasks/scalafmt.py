# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from abc import abstractproperty

from pants.backend.jvm.tasks.rewrite_base import RewriteBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.collections import assert_single_element


class ScalaFmt(RewriteBase):
  """Abstract class to run ScalaFmt commands.

  Classes that inherit from this should override additional_args and
  process_result to run different scalafmt commands.
  """

  @classmethod
  def register_options(cls, register):
    super(ScalaFmt, cls).register_options(register)
    register('--configuration', advanced=True, type=file_option, fingerprint=True,
              help='Path to scalafmt config file, if not specified default scalafmt config used')

    cls.register_jvm_tool(
      register,
      'scalafmt',
      classpath=[
        JarDependency(org='com.geirsson',
                      name='scalafmt-cli_2.11',
                      rev='1.5.1'),
        # NB!!!!: the version here should match the major and minor version used for the tool, and
        # should be the latest release for the (maj,min) tuple
        # TODO: this requires the user to specify the scala-reflect jar dependency in BUILD.tools or
        # wherever the scalafmt dep is defined.
        # TODO: this should only be if we use the graal executor!
        JarDependency(org='org.scala-lang',
                      name='scala-reflect',
                      rev='2.11.12'),
      ])

  @classmethod
  def target_types(cls):
    return ['scala_library', 'junit_tests', 'java_tests']

  @classmethod
  def source_extension(cls):
    return '.scala'

  @classmethod
  def implementation_version(cls):
    return super(ScalaFmt, cls).implementation_version() + [('ScalaFmt', 5)]

  def invoke_tool(self, absolute_root, target_sources):
    # If no config file is specified use default scalafmt config.
    config_file = self.get_options().configuration
    args = list(self.additional_args)
    if config_file is not None:
      if not os.path.isabs(config_file):
        config_file = os.path.join(get_buildroot(), config_file)
      args.extend(['--config', config_file])
    args.extend([source for _target, source in target_sources])

    # If the scalafmt target or any of its transitive dependencies have changed, this fingerprint
    # will be different -- this is currently only used in the graal executor.
    # TODO: `input_fingerprint` should be calculated automatically from the jvm tool target option
    # in runjava, or in a new API somewhere (otherwise it will just error out in the graal
    # subsystem)
    scalafmt_target = assert_single_element(
      self.context.build_graph.resolve(self.get_options().scalafmt))
    input_fingerprint = scalafmt_target.transitive_invalidation_hash()

    return self.runjava(classpath=self.tool_classpath('scalafmt'),
                        main='org.scalafmt.cli.Cli',
                        args=args,
                        workunit_name='scalafmt',
                        jvm_options=self.get_options().jvm_options,
                        input_fingerprint=input_fingerprint)

  @abstractproperty
  def additional_args(self):
    """Returns the arguments used to run Scalafmt command.

    The return value should be an array of strings.  For
    example, to run the Scalafmt help command:
    ['--help']
    """


class ScalaFmtCheckFormat(LintTaskMixin, ScalaFmt):
  """This Task checks that all scala files in the target are formatted
  correctly.

  If the files are not formatted correctly an error is raised
  including the command to run to format the files correctly

  :API: public
  """

  sideeffecting = False
  additional_args = ['--test']

  def process_result(self, result):
    if result != 0:
      raise TaskError('Scalafmt failed with exit code {}; to fix run: '
                      '`./pants fmt <targets>`'.format(result), exit_code=result)


class ScalaFmtFormat(FmtTaskMixin, ScalaFmt):
  """This Task reads all scala files in the target and emits
  the source in a standard style as specified by the configuration
  file.

  This task mutates the underlying flies.

  :API: public
  """

  sideeffecting = True
  additional_args = ['-i']

  def process_result(self, result):
    # Processes the results of running the scalafmt command.
    if result != 0:
      raise TaskError('Scalafmt failed to format files', exit_code=result)
