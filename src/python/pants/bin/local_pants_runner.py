# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from builtins import object, str

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, Exiter
from pants.base.workunit import WorkUnit
from pants.bin.goal_runner import GoalRunner
from pants.engine.native import Native
from pants.goal.run_tracker import RunTracker
from pants.init.engine_initializer import EngineInitializer
from pants.init.logging import setup_logging_from_options
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.init.repro import Reproducer
from pants.init.target_roots_calculator import TargetRootsCalculator
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.reporting.reporting import Reporting
from pants.rules.core.exceptions import GracefulTerminationException
from pants.util.contextutil import maybe_profiled


logger = logging.getLogger(__name__)


class LocalExiter(Exiter):

  def __init__(self, run_tracker, repro, *args, **kwargs):
    self._run_tracker = run_tracker
    self._repro = repro
    super(LocalExiter, self).__init__(*args, **kwargs)

  def exit(self, result=PANTS_SUCCEEDED_EXIT_CODE, msg=None, *args, **kwargs):
    # These strings are prepended to the existing exit message when calling the superclass .exit().
    additional_messages = []
    try:
      if not self._run_tracker.has_ended():
        if result == PANTS_SUCCEEDED_EXIT_CODE:
          outcome = WorkUnit.SUCCESS
        elif result == PANTS_FAILED_EXIT_CODE:
          outcome = WorkUnit.FAILURE
        else:
          run_tracker_msg = ("unrecognized exit code {} provided to {}.exit() -- "
                             "interpreting as a failure in the run tracker"
                             .format(result, type(self).__name__))
          # Log the unrecognized exit code to the fatal exception log.
          ExceptionSink.log_exception(run_tracker_msg)
          # Ensure the unrecognized exit code message is also logged to the terminal.
          additional_messages.push(run_tracker_msg)
          outcome = WorkUnit.FAILURE

        self._run_tracker.set_root_outcome(outcome)
        run_tracker_result = self._run_tracker.end()
        assert result == run_tracker_result, "pants exit code not correctly recorded by run tracker"
    except ValueError as e:
      # If we have been interrupted by a signal, calling .end() sometimes writes to a closed file,
      # so we just log that fact here and keep going.
      exception_string = str(e)
      ExceptionSink.log_exception(exception_string)
      additional_messages.push(exception_string)
    finally:
      if self._repro:
        # TODO: Have Repro capture the 'after' state (as a diff) as well? (in reference to the below
        # 'before' state comment)
        # NB: this writes to the logger, which is expected to still be alive if we are exiting from
        # a signal.
        self._repro.log_location_of_repro_file()

    if additional_messages:
      msg = '{}\n\n{}'.format('\n'.join(additional_messages),
                              msg or '')

    super(LocalExiter, self).exit(result=result, msg=msg, *args, **kwargs)


class LocalPantsRunner(object):
  """Handles a single pants invocation running in the process-local context."""

  @staticmethod
  def parse_options(args, env, setup_logging=False, options_bootstrapper=None):
    options_bootstrapper = options_bootstrapper or OptionsBootstrapper.create(args=args, env=env)
    bootstrap_options = options_bootstrapper.get_bootstrap_options().for_global_scope()
    if setup_logging:
      # Bootstrap logging and then fully initialize options.
      setup_logging_from_options(bootstrap_options)
    build_config = BuildConfigInitializer.get(options_bootstrapper)
    options = OptionsInitializer.create(options_bootstrapper, build_config)
    return options, build_config, options_bootstrapper

  @staticmethod
  def _maybe_init_graph_session(graph_session, options_bootstrapper,build_config, options):
    if graph_session:
      return graph_session

    native = Native()
    native.set_panic_handler()
    graph_scheduler_helper = EngineInitializer.setup_legacy_graph(
      native,
      options_bootstrapper,
      build_config
    )

    v2_ui = options.for_global_scope().v2_ui
    zipkin_trace_v2 = options.for_scope('reporting').zipkin_trace_v2
    return graph_scheduler_helper.new_session(zipkin_trace_v2, v2_ui)

  @staticmethod
  def _maybe_init_target_roots(target_roots, graph_session, options, build_root):
    if target_roots:
      return target_roots

    global_options = options.for_global_scope()
    return TargetRootsCalculator.create(
      options=options,
      build_root=build_root,
      session=graph_session.scheduler_session,
      symbol_table=graph_session.symbol_table,
      exclude_patterns=tuple(global_options.exclude_target_regexp),
      tags=tuple(global_options.tag)
    )

  @classmethod
  def create(cls, exiter, args, env, target_roots=None, daemon_graph_session=None,
             options_bootstrapper=None):
    """Creates a new LocalPantsRunner instance by parsing options.

    :param Exiter exiter: The Exiter instance to use for this run.
    :param list args: The arguments (e.g. sys.argv) for this run.
    :param dict env: The environment (e.g. os.environ) for this run.
    :param TargetRoots target_roots: The target roots for this run.
    :param LegacyGraphSession daemon_graph_session: The graph helper for this session.
    :param OptionsBootstrapper options_bootstrapper: The OptionsBootstrapper instance to reuse.
    """
    build_root = get_buildroot()

    options, build_config, options_bootstrapper = cls.parse_options(
      args,
      env,
      True,
      options_bootstrapper
    )
    global_options = options.for_global_scope()

    # Option values are usually computed lazily on demand,
    # but command line options are eagerly computed for validation.
    for scope in options.scope_to_flags.keys():
      options.for_scope(scope)

    # Verify configs.
    if global_options.verify_config:
      options_bootstrapper.verify_configs_against_options(options)

    # If we're running with the daemon, we'll be handed a session from the
    # resident graph helper - otherwise initialize a new one here.
    graph_session = cls._maybe_init_graph_session(
      daemon_graph_session,
      options_bootstrapper,
      build_config,
      options
    )

    target_roots = cls._maybe_init_target_roots(
      target_roots,
      graph_session,
      options,
      build_root
    )

    profile_path = env.get('PANTS_PROFILE')

    return cls(
      build_root,
      exiter,
      options,
      options_bootstrapper,
      build_config,
      target_roots,
      graph_session,
      daemon_graph_session is not None,
      profile_path
    )

  def __init__(self, build_root, exiter, options, options_bootstrapper, build_config, target_roots,
               graph_session, is_daemon, profile_path):
    """
    :param string build_root: The build root for this run.
    :param Exiter exiter: The Exiter instance to use for this run.
    :param Options options: The parsed options for this run.
    :param OptionsBootstrapper options_bootstrapper: The OptionsBootstrapper instance to use.
    :param BuildConfiguration build_config: The parsed build configuration for this run.
    :param TargetRoots target_roots: The `TargetRoots` for this run.
    :param LegacyGraphSession graph_session: A LegacyGraphSession instance for graph reuse.
    :param bool is_daemon: Whether or not this run was launched with a daemon graph helper.
    :param string profile_path: The profile path - if any (from from the `PANTS_PROFILE` env var).
    """
    self._build_root = build_root
    self._exiter = exiter
    self._options = options
    self._options_bootstrapper = options_bootstrapper
    self._build_config = build_config
    self._target_roots = target_roots
    self._graph_session = graph_session
    self._is_daemon = is_daemon
    self._profile_path = profile_path

    self._run_start_time = None
    self._run_tracker = None
    self._reporting = None
    self._repro = None
    self._global_options = options.for_global_scope()

  def set_start_time(self, start_time):
    # Launch RunTracker as early as possible (before .run() is called).
    self._run_tracker = RunTracker.global_instance()
    self._reporting = Reporting.global_instance()

    self._run_start_time = start_time
    self._reporting.initialize(self._run_tracker, self._options, start_time=self._run_start_time)

    # Capture a repro of the 'before' state for this build, if needed.
    self._repro = Reproducer.global_instance().create_repro()
    if self._repro:
      self._repro.capture(self._run_tracker.run_info.get_as_dict())

    # The __call__ method of the Exiter allows for the prototype pattern.
    self._exiter = LocalExiter(self._run_tracker, self._repro, exiter=self._exiter)
    ExceptionSink.reset_exiter(self._exiter)

  def run(self):
    with maybe_profiled(self._profile_path):
      self._run()

  def _maybe_run_v1(self):
    if not self._global_options.v1:
      return PANTS_SUCCEEDED_EXIT_CODE

    # Setup and run GoalRunner.
    goal_runner_factory = GoalRunner.Factory(
      self._build_root,
      self._options,
      self._build_config,
      self._run_tracker,
      self._reporting,
      self._graph_session,
      self._target_roots,
      self._exiter
    )
    return goal_runner_factory.create().run()

  def _maybe_run_v2(self):
    # N.B. For daemon runs, @console_rules are invoked pre-fork -
    # so this path only serves the non-daemon run mode.
    if self._is_daemon or not self._global_options.v2:
      return PANTS_SUCCEEDED_EXIT_CODE

    # If we're a pure --v2 run, validate goals - otherwise some goals specified
    # may be provided by the --v1 task paths.
    if not self._global_options.v1:
      self._graph_session.validate_goals(self._options.goals_and_possible_v2_goals)

    try:
      self._graph_session.run_console_rules(
        self._options_bootstrapper,
        self._options.goals_and_possible_v2_goals,
        self._target_roots,
      )
    except GracefulTerminationException as e:
      logger.debug('Encountered graceful termination exception {}; exiting'.format(e))
      return e.exit_code
    except Exception as e:
      logger.warn('Encountered unhandled exception {} during rule execution!'
                  .format(e))
      return PANTS_FAILED_EXIT_CODE
    else:
      return PANTS_SUCCEEDED_EXIT_CODE

  @staticmethod
  def _compute_final_exit_code(*codes):
    """Returns the exit code with higher abs value in case of negative values."""
    max_code = None
    for code in codes:
      if max_code is None or abs(max_code) < abs(code):
        max_code = code
    return max_code

  def _run(self):
    try:
      engine_result = self._maybe_run_v2()
      goal_runner_result = self._maybe_run_v1()
    finally:
      try:
        run_tracker_result = self._run_tracker.end()
      except ValueError as e:
        # Calling .end() sometimes writes to a closed file, so we return a dummy result here.
        logger.exception(e)
        run_tracker_result = PANTS_SUCCEEDED_EXIT_CODE

    final_exit_code = self._compute_final_exit_code(
      engine_result,
      goal_runner_result,
      run_tracker_result
    )
    self._exiter.exit(final_exit_code)
