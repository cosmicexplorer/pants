# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from future.utils import binary_type, text_type

from pants.engine.fs import DirectoryDigest
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.objects import DatatypeFieldDecl as F
from pants.util.objects import Exactly, TypeCheckError, convert, convert_default, datatype, optional


logger = logging.getLogger(__name__)

_default_timeout_seconds = 15 * 60


def _parse_env_to_tuple(env=None):
  if env is None:
    env = ()
  elif isinstance(env, dict):
    env = tuple(item for pair in env.items() for item in pair)
  else:
    raise TypeError(
      "env was invalid: value {!r} (with type '{}') must be a dict or None."
      .format(env, type(env).__name__))

  return env


class ExecuteProcessRequest(datatype([
    ('argv', tuple),
    ('input_files', DirectoryDigest),
    ('description', text_type),
    F('env', convert(tuple, create_func=_parse_env_to_tuple), default_value=None),
    ('output_files', convert_default(tuple)),
    ('output_directories', convert_default(tuple)),
    # NB: timeout_seconds covers the whole remote operation including queuing and setup.
    F('timeout_seconds', Exactly(float, int), default_value=_default_timeout_seconds),
    ('jdk_home', optional(text_type)),
])):
  """Request for execution with args and snapshots to extract."""


class ExecuteProcessResult(datatype([
    ('stdout', binary_type),
    ('stderr', binary_type),
    ('output_directory_digest', DirectoryDigest),
])):
  """Result of successfully executing a process.

  Requesting one of these will raise an exception if the exit code is non-zero."""


class FallibleExecuteProcessResult(datatype([
    ('stdout', binary_type),
    ('stderr', binary_type),
    ('exit_code', int),
    ('output_directory_digest', DirectoryDigest),
])):
  """Result of executing a process.

  Requesting one of these will not raise an exception if the exit code is non-zero."""


class ProcessExecutionFailure(Exception):
  """Used to denote that a process exited, but was unsuccessful in some way.

  For example, exiting with a non-zero code.
  """

  MSG_FMT = """process '{desc}' failed with exit code {code}.
stdout:
{stdout}
stderr:
{stderr}
"""

  def __init__(self, exit_code, stdout, stderr, process_description):
    # These are intentionally "public" members.
    self.exit_code = exit_code
    self.stdout = stdout
    self.stderr = stderr

    msg = self.MSG_FMT.format(
      desc=process_description, code=exit_code, stdout=stdout, stderr=stderr)

    super(ProcessExecutionFailure, self).__init__(msg)


@rule(ExecuteProcessResult, [Select(FallibleExecuteProcessResult), Select(ExecuteProcessRequest)])
def fallible_to_exec_result_or_raise(fallible_result, request):
  """Converts a FallibleExecuteProcessResult to a ExecuteProcessResult or raises an error."""

  if fallible_result.exit_code == 0:
    return ExecuteProcessResult(
      fallible_result.stdout,
      fallible_result.stderr,
      fallible_result.output_directory_digest
    )
  else:
    raise ProcessExecutionFailure(
      fallible_result.exit_code,
      fallible_result.stdout,
      fallible_result.stderr,
      request.description
    )


def create_process_rules():
  """Creates rules that consume the intrinsic filesystem types."""
  return [
    RootRule(ExecuteProcessRequest),
    fallible_to_exec_result_or_raise
  ]
