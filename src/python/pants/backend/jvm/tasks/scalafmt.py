# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from abc import abstractproperty

from twitter.common.collections import OrderedSet

from pants.backend.jvm.tasks.rewrite_base import RewriteBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.collections import assert_single_element
from pants.util.process_handler import SubprocessProcessHandler


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
    register('--files-per-process', type=int, default=0, advanced=True,
             help='If nonzero, split all the relevant source files into this many files per'
                  'subprocess invoked in parallel.')

    cls.register_jvm_tool(
      register,
      'scalafmt',
      classpath=[
        JarDependency(org='com.geirsson',
                      name='scalafmt-cli_2.11',
                      rev='1.5.1'),
        # NB: Scalafmt has specifically added support for graal, and other tools may need to as
        # well.  The version here should match the major and minor scala version used for the tool,
        # and should be the latest release for the (maj,min) tuple.
        # If the user overrides the scalafmt dependency, e.g. in BUILD.tools, this would require the
        # user to specify the scala-reflect jar dependency where the override occurs in order to
        # work with graal.
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

  # TODO: if we want to address scalafmt perf in general, we should first ensure we only operate on
  # the files which were specifically changed, not all files in all invalidated targets! The
  # _calculate_sources() method is probably the one to change here.
  def _execute_for(self, targets):
    """If parallelism is enabled, spawn a process per target and wait on them all."""
    num_files_per_proc = self.get_options().files_per_process
    if num_files_per_proc == 0:
      return super(ScalaFmt, self)._execute_for(targets)

    # TODO: split by cumulative file size, not by number of files!
    # Get a list of all sources from all targets and deduplicate by relative file path.
    all_sources = list(OrderedSet(
      s for tgt in targets for _, s in self._calculate_sources([tgt])
    ))

    sources_per_process = [
      all_sources[x:x+num_files_per_proc]
      for x in xrange(0, len(all_sources), num_files_per_proc)
    ]
    with self.context.new_workunit('scalafmt-multiprocessing') as workunit:
      subprocs = [
        # TODO: need to use different workunits or something to avoid the FAILURE because when
        # multiple workunits complete they all try to write to the closed output streams.
        self.invoke_tool_async(srcs)
        for srcs in sources_per_process
      ]
      gone, alive = SubprocessProcessHandler.wait_all(subprocs)
      assert(len(alive) == 0)

      for completed_proc in gone:
        rc = completed_proc.returncode
        if rc != 0:
          # TODO: expand this!
          raise TaskError('Subprocess exited with nonzero code {}.'.format(rc))

      workunit.set_outcome(WorkUnit.SUCCESS)

  # TODO: remove the repeated boilerplate here!
  def invoke_tool_async(self, target_sources):
    # If no config file is specified, use default scalafmt config.
    config_file = self.get_options().configuration
    args = list(self.additional_args)
    if config_file is not None:
      if not os.path.isabs(config_file):
        config_file = os.path.join(get_buildroot(), config_file)
      args.extend(['--config', config_file])
    args.extend(target_sources)

    return self.runjava(classpath=self.tool_classpath('scalafmt'),
                        main='org.scalafmt.cli.Cli',
                        args=args,
                        workunit_name='scalafmt',
                        jvm_options=self.get_options().jvm_options,
                        async=True)

  def invoke_tool(self, absolute_root, target_sources):
    # If no config file is specified use default scalafmt config.
    config_file = self.get_options().configuration
    args = list(self.additional_args)
    if config_file is not None:
      if not os.path.isabs(config_file):
        config_file = os.path.join(get_buildroot(), config_file)
      args.extend(['--config', config_file])
    args.extend([source for _target, source in target_sources])

    return self.runjava(classpath=self.tool_classpath('scalafmt'),
                        main='org.scalafmt.cli.Cli',
                        args=args,
                        workunit_name='scalafmt',
                        jvm_options=self.get_options().jvm_options,
                        async=False)

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
