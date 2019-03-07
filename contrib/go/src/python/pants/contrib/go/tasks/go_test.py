# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from contextlib import contextmanager

from future.utils import text_type
from pants.base.build_environment import get_buildroot
from pants.base.workunit import WorkUnitLabel
from pants.task.testrunner_task_mixin import PartitionedTestRunnerTaskMixin, TestResult
from pants.util.memo import memoized_property
from pants.util.objects import datatype
from pants.util.process_handler import SubprocessProcessHandler
from pants.util.strutil import create_path_env_var, safe_shlex_join, safe_shlex_split

from pants.contrib.go.tasks.go_workspace_task import GoWorkspaceTask


class GoTest(PartitionedTestRunnerTaskMixin, GoWorkspaceTask):
  """Runs `go test` on Go packages.

  To run a library's tests, GoTest only requires a Go workspace to be initialized
  (see GoWorkspaceTask) with links to necessary source files. It does not require
  GoCompile to first compile the library to be tested -- in fact, GoTest will ignore
  any binaries in "$GOPATH/pkg/", because Go test files (which live in the package
  they are testing) are ignored in normal compilation, so Go test must compile everything
  from scratch.
  """

  @classmethod
  def register_options(cls, register):
    super(GoTest, cls).register_options(register)
    # TODO: turn these into a list of individually-shlexed strings and deprecate using a single
    # string!
    register('--build-and-test-flags', default='',
             fingerprint=True,
             help='Flags to pass in to `go test` tool.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def _test_target_filter(self):
    """Filter for targets with test files which are specified on the command line.

    Because go libraries have test sources within the same target, we explicitly avoid going through
    the dependencies of the target roots, or we'd be running tests on every source dependency.
    """
    def filt(tgt):
      is_test_target_on_cmdline = tgt in self.context.target_roots and self.is_test_target(tgt)
      return is_test_target_on_cmdline
    return filt

  def _validate_target(self, target):
    self.ensure_workspace(target)

  class _GoTestTargetInfo(datatype([
      ('import_path', text_type),
      ('gopath', text_type),
  ])): pass

  def _generate_args_for_targets(self, targets):
    """
    Generate a dict mapping target -> _GoTestTargetInfo so that the import path and gopath can be
    reconstructed for spawning test commands regardless of how the targets are partitioned.
    """
    return {
      t: self._GoTestTargetInfo(import_path=t.import_path, gopath=self.get_gopath(t))
      for t in targets
    }

  @contextmanager
  def partitions(self, per_target, all_targets, test_targets):
    if per_target:
      def iter_partitions():
        for test_target in test_targets:
          partition = (test_target,)
          args = (self._generate_args_for_targets([test_target]),)
          yield partition, args
    else:
      def iter_partitions():
        if test_targets:
          partition = tuple(test_targets)
          args = (self._generate_args_for_targets(test_targets),)
          yield partition, args
    yield iter_partitions

  def collect_files(self, *args):
    pass

  @memoized_property
  def _build_and_test_flags(self):
    return safe_shlex_split(self.get_options().build_and_test_flags)

  def _spawn(self, workunit, go_cmd, cwd):
    go_process = go_cmd.spawn(cwd=cwd,
                              stdout=workunit.output('stdout'),
                              stderr=workunit.output('stderr'))
    return SubprocessProcessHandler(go_process)

  @property
  def _maybe_workdir(self):
    if self.run_tests_in_chroot:
      return None
    return get_buildroot()

  def run_tests(self, fail_fast, test_targets, args_by_target):
    self.context.log.debug('test_targets: {}'.format(test_targets))
    if not test_targets:
      return TestResult.successful

    with self.chroot(test_targets, self._maybe_workdir) as chroot:
      cmdline_args = self._build_and_test_flags + [
        args_by_target[t].import_path for t in test_targets
      ] + self.get_passthru_args()
      gopath = create_path_env_var(
        args_by_target[t].gopath for t in test_targets
      )
      go_cmd = self.go_dist.create_go_cmd('test', gopath=gopath, args=cmdline_args)

      self.context.log.debug('go_cmd: {}'.format(go_cmd))

      workunit_labels = [WorkUnitLabel.TOOL, WorkUnitLabel.TEST]
      with self.context.new_workunit(
          name='go test', cmd=safe_shlex_join(go_cmd.cmdline), labels=workunit_labels) as workunit:

        exit_code = self.spawn_and_wait(workunit=workunit, go_cmd=go_cmd, cwd=chroot)
        return TestResult.rc(exit_code)
