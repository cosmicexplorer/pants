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
from pants.util.dirutil import is_writable_dir, safe_open


logger = logging.getLogger(__name__)


class ExceptionSink(object):
  """A mutable singleton object representing where exceptions should be logged to."""

  # Get the current directory at class initialization time -- this is probably (definitely?) a
  # writable directory. Using this directory as a fallback increases the chances that if an
  # exception occurs early in initialization that we still record it somewhere.
  _destination = os.getcwd()
  _traceback_formatter = None
  _trace_stream = None
  _exiter = None

  def __new__(cls, *args, **kwargs):
    raise TypeError('Instances of {} are not allowed to be constructed!'
                    .format(cls.__name__))

  class ExceptionSinkError(Exception): pass

  @classmethod
  def reset_fatal_error_logging(cls,
                                destination=None,
                                traceback_formatter=traceback.format_tb,
                                trace_stream=None,
                                exiter=None):
    # TODO: We maintain the current log destination if not overridden -- we could also keep previous
    # values of cls._destination as a list and fall back in order to previous log dirs if logging
    # fails to the current destination. Resetting the log destination doesn't happen often enough to
    # justify this now.
    destination = destination or cls._destination
    if not is_writable_dir(destination):
      # TODO: when this class sets up excepthooks, raising this should be safe, because we always
      # have a destination to log to (os.getcwd() if not otherwise set).
      raise cls.ExceptionSinkError(
        "The provided exception sink path at '{}' is not a writable directory."
        .format(destination))
    cls._destination = destination

    # None is an allowed value -- this does not print tracebacks.
    cls._traceback_formatter = traceback_formatter

    cls._trace_stream = trace_stream or sys.stderr

    cls._exiter = exiter or Exiter()

    # TODO: verify that these faulthandler operations are idempotent!
    faulthandler.enable(cls._trace_stream)
    # This permits a non-fatal `kill -31 <pants pid>` for stacktrace retrieval.
    faulthandler.register(signal.SIGUSR2, cls._trace_stream, chain=True)

    # Make unhandled exceptions go to our exception log now.
    sys.excepthook = cls._handle_unhandled_exception

    # TODO: this should handle control-c as well. This may require a SIGINT handler and a check for
    # KeyboardInterrupt in the exception hook?
    signal.signal(signal.SIGINT, cls._handle_sigint)

  @classmethod
  def _exceptions_log_path(cls, for_pid=None):
    intermediate_filename_component = '.{}'.format(for_pid) if for_pid else ''
    return os.path.join(
      cls.get_destination(),
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
  def _format_exception_message(cls, msg, pid):
    return cls._EXCEPTION_LOG_FORMAT.format(
      timestamp=cls._iso_timestamp_for_now(),
      args=sys.argv,
      pid=pid,
      message=msg,
    )

  @classmethod
  def log_exception(cls, msg):
    try:
      pid = os.getpid()
      fatal_error_log_entry = cls._format_exception_message(msg, pid)
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
    if cls._traceback_formatter is None:
      return '(backtrace omitted)'
    else:
      return cls._traceback_formatter(tb)

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
  def _handle_unhandled_exception(cls, exc_class=None, exc=None, tb=None, add_newline=False):
    """Default sys.excepthook implementation for unhandled exceptions."""
    exc_class = exc_class or sys.exc_info()[0]
    exc = exc or sys.exc_info()[1]
    tb = tb or sys.exc_info()[2]

    # Always output the unhandled exception details into a log file.
    exception_log_entry = cls._format_unhandled_exception_log(exc, tb, add_newline)
    cls.log_exception(exception_log_entry)

  @classmethod
  def _handle_sigint(cls, signum, frame):
    raise KeyboardInterrupt('???')


# NB: We set all our class attributes to the default values by calling this method at module import
# time.
ExceptionSink.reset_fatal_error_logging()
