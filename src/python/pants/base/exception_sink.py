# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import faulthandler
import logging
import os
import signal
import sys
import traceback
from builtins import object, str

from pants.base.exiter import Exiter
from pants.util.dirutil import safe_mkdir, safe_open


logger = logging.getLogger(__name__)


class SignalHandler(object):

  # Handle ^C signals and convert them into a KeyboardInterrupt.
  def handle_sigint(self, signum, frame):
    raise KeyboardInterrupt('^C (SIGINT) received from user.')

  # TODO: this shouldn't always copy SIGINT, but the signal handlers should both be set every time
  # to avoid inconsistent logging.
  def handle_sigquit(self, signum, frame):
    self.handle_sigint(signum, frame)

  def _apply_global_signal_changes(self):
    signal.signal(signal.SIGINT, self.handle_sigint)
    signal.signal(signal.SIGQUIT, self.handle_sigquit)

    # Retry interrupted system calls.
    signal.siginterrupt(signal.SIGINT, False)
    signal.siginterrupt(signal.SIGQUIT, False)


class ExceptionSink(object):
  """A mutable singleton object representing where exceptions should be logged to."""

  # Get the current directory at class initialization time -- this is probably (definitely?) a
  # writable directory. Using this directory as a fallback increases the chances that if an
  # exception occurs early in initialization that we still record it somewhere.
  _destination = None
  _should_print_backtrace = True
  _trace_stream = None
  _exiter = Exiter()
  _signal_handler = None

  def __new__(cls, *args, **kwargs):
    raise TypeError('Instances of {} are not allowed to be constructed!'
                    .format(cls.__name__))

  class ExceptionSinkError(Exception): pass

  @classmethod
  def reset_fatal_error_logging_from_options(cls, maybe_options=None, **kwargs):
    kw = kwargs.copy()
    if maybe_options:
      if 'destination' not in kw:
        kw['destination'] = maybe_options.pants_workdir
      if 'should_print_backtrace' not in kw:
        kw['should_print_backtrace'] = maybe_options.print_exception_stacktrace

    cls.reset_fatal_error_logging(**kw)

  @classmethod
  def reset_fatal_error_logging(cls,
                                destination=None,
                                should_print_backtrace=True,
                                trace_stream=None,
                                exiter=None,
                                signal_handler=None):
    # TODO: We maintain the current log destination if not overridden -- we could also keep previous
    # values of cls._destination as a list and fall back in order to previous log dirs if logging
    # fails to the current destination. Resetting the log destination doesn't happen often enough to
    # justify this now.
    if destination:
      logger.debug("attempted new fatal log destination: '{}'.".format(destination))
      cls._destination = cls._check_or_create_new_destination(destination)
      logger.debug("fatal log destination at '{}' was successful!".format(cls._destination))

    cls._should_print_backtrace = should_print_backtrace
    logger.debug("should_print_backtrace is now set to: {}.".format(cls._should_print_backtrace))

    # TODO: should this be folded into SignalHandler?
    if trace_stream:
      # TODO: Is the 'name' attribute going to be on every file in supported pythons?
      stream_name = getattr(trace_stream, 'name', '(no name provided for stream)')
      logger.debug("trace_stream will be prepared to create stacktraces on SIGUSR2: '{}'."
                   .format(stream_name))
      # NB: GLOBAL STATE CHANGE
      # This permits a non-fatal `kill -31 <pants pid>` for stacktrace retrieval.
      if faulthandler.is_enabled():
        faulthandler.disable()
      faulthandler.enable(trace_stream)
      faulthandler.register(signal.SIGUSR2, trace_stream, chain=True)
      # TODO: do we need to keep a reference to the trace stream and signal handler objects?
      # cls._trace_stream = trace_stream
      logger.debug("trace_stream was successfully used to create stacktraces on SIGUSR2: '{}'!"
                   .format(stream_name))

    if exiter:
      cls._exiter = exiter
      logger.debug("new exiter: {!r}.".format(exiter))

    if signal_handler:
      logger.debug("signal_handler will reset signal handling: {!r}.".format(signal_handler))
      # NB: GLOBAL STATE CHANGE
      signal_handler._apply_global_signal_changes()
      cls._signal_handler = signal_handler
      logger.debug("signal_handler successfully reset signal handling: {!r}!"
                   .format(cls._signal_handler))

    # NB: GLOBAL STATE CHANGE
    # Make unhandled exceptions go to our exception log now.
    sys.excepthook = cls._log_unhandled_exception_and_exit

  @classmethod
  def _check_or_create_new_destination(cls, destination):
    try:
      safe_mkdir(destination)
    except Exception as e:
      # NB: When this class sets up excepthooks, raising this should be safe, because we always
      # have a destination to log to (os.getcwd() if not otherwise set).
      raise cls.ExceptionSinkError(
        "The provided exception sink path at '{}' is not writable and could not be created: {}."
        .format(destination, str(e)),
        e)
    return destination

  @classmethod
  def _exceptions_log_path(cls, for_pid=None):
    intermediate_filename_component = '.{}'.format(for_pid) if for_pid else ''
    return os.path.join(
      cls._destination,
      'logs',
      'exceptions{}.log'.format(intermediate_filename_component))

  @classmethod
  def _iso_timestamp_for_now(cls):
    return datetime.datetime.now().isoformat()

  # NB: This includes a trailing newline, but no leading newline.
  _FATAL_ERROR_LOG_FORMAT = """\
timestamp: {timestamp}
args: {args}
pid: {pid}
{message}
"""

  @classmethod
  def _format_fatal_error_log(cls, msg, pid):
    return cls._FATAL_ERROR_LOG_FORMAT.format(
      timestamp=cls._iso_timestamp_for_now(),
      args=sys.argv,
      pid=pid,
      message=msg,
    )

  @classmethod
  def log_exception(cls, msg):
    try:
      pid = os.getpid()
      fatal_error_log_entry = cls._format_fatal_error_log(msg, pid)
      # We care more about this log than the shared log, so completely write to it first. This
      # avoids any errors with concurrent modification of the shared log affecting the per-pid log.
      with safe_open(cls._exceptions_log_path(for_pid=pid), 'a') as pid_error_log:
        pid_error_log.write(fatal_error_log_entry)
      # TODO: we should probably guard this against concurrent modification somehow.
      with safe_open(cls._exceptions_log_path(), 'a') as shared_error_log:
        shared_error_log.write(fatal_error_log_entry)
    except Exception as e:
      # TODO: update the below TODO!
      # TODO: If there is an error in writing to the exceptions log, we may want to consider trying
      # to write to another location (e.g. the cwd, if that is not already the destination).
      logger.error('Problem logging original exception: {}'.format(e))

  @classmethod
  def _format_traceback(cls, tb):
    if cls._should_print_backtrace:
      traceback_string = ''.join(traceback.format_tb(tb))
    else:
      traceback_string = '(backtrace omitted)'
    return traceback_string

  _UNHANDLED_EXCEPTION_LOG_FORMAT = """\
Exception caught: ({exception_type})
{backtrace}
Exception message: {exception_message}{maybe_newline}
"""

  @classmethod
  def _format_unhandled_exception_log(cls, exc, tb, add_newline):
    exception_message = str(exc) if exc else '(no message)'
    maybe_newline = '\n' if add_newline else ''
    return cls._UNHANDLED_EXCEPTION_LOG_FORMAT.format(
      exception_type=type(exc),
      backtrace=cls._format_traceback(tb),
      exception_message=exception_message,
      maybe_newline=maybe_newline,
    )

  @classmethod
  def _log_unhandled_exception_and_exit(cls, exc_class=None, exc=None, tb=None, add_newline=False):
    """Default sys.excepthook implementation for unhandled exceptions."""
    exc_class = exc_class or sys.exc_info()[0]
    exc = exc or sys.exc_info()[1]
    tb = tb or sys.exc_info()[2]

    # Always output the unhandled exception details into a log file.
    exception_log_entry = cls._format_unhandled_exception_log(exc, tb, add_newline)
    cls.log_exception(exception_log_entry)

    # TODO: what to print here?
    cls._exiter.exit(result=1, msg=exception_log_entry)


# NB: We setup exception hooks by calling this method at at module import time in order to catch
# fatal errors early on.
ExceptionSink.reset_fatal_error_logging(
  destination=os.getcwd(),
  trace_stream=sys.stderr,
  signal_handler=SignalHandler(),
)
