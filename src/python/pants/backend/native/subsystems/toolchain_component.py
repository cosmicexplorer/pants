# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from abc import abstractmethod

from pants.subsystem.subsystem import Subsystem
from pants.util.objects import datatype
from pants.util.process_handler import subprocess


class NativeBuildExecutionRequest(datatype('NativeBuildExecutionRequest', [
      'argv',
      'env',
      'cwd',
      'output_file_paths',
])): pass


class NativeBuildExecutionResult(datatype('NativeBuildExecutionResult', [
    'output',
    'output_files',
])): pass


class ToolchainComponent(Subsystem):

  @abstractmethod
  def make_execution_request(self, sources): pass

  @abstractmethod
  def wrap_

  class InvocationError(Exception): pass

  def _format_argv(self, argv):
    return ' '.join(["'{}'".format(arg) for arg in argv])

  def _collect_outputs(self, request, output):
    result_paths = set()

    for output_path in request.output_file_paths:
      joined_path = os.path.join(request.cwd, output_path)
      real_path = os.path.realpath(joined_path)

      if not os.path.isfile(real_path):
        raise self.InvocationError(
          "expected output file '{}' does not exist! (from request: '{}')"
          .format(output_path, repr(request)))

      result_paths.add(real_path)

    return NativeBuildExecutionResult(output=output, output_files=result_paths)

  def invoke(self, sources):
    request = self.make_execution_request(sources)

    if not os.path.isdir(request.cwd):
      raise self.InvocationError(
        "cwd '{}' does not exist! (for request '{}')"
        .format(request.cwd, repr(request)))
    if not request.output_file_paths:
      raise self.InvocationError(
        "no output_file_paths specified for execution request '{}'"
        .format(repr(request)))

    try:
      merged_stdout_stderr = subprocess.check_output(
        args=request.argv,
        cwd=request.cwd,
        env=request.env)

      return self._collect_outputs(request, merged_stdout_stderr)

    except subprocess.CalledProcessError as e:
      raise self.InvocationError(
        "Command {cmd} failed with code {code}. "
        "env={env}, output:\n{output}"
        .format(
          cmd=self._format_argv(execution.argv),
          code=e.returncode,
          env=execution.env,
          output=e.output,
        ))
