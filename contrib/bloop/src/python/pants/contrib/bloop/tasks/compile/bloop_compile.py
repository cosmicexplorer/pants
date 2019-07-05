# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
from abc import abstractmethod

from pants.backend.jvm.subsystems.zinc import Zinc
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.engine.rules import RootRule, UnionRule, rule, union
from pants.engine.selectors import Get
from pants.java.jar.jar_dependency import JarDependency
from pants.util.meta import AbstractClass
from pants.util.objects import SubclassesOf, datatype, enum_struct, string_list
from pants.util.process_handler import ProcessHandler, subprocess


class BloopHackyProtocol(AbstractClass):

  @classmethod
  @abstractmethod
  def parse_from_json(cls, json_obj):
    """???"""


class BloopCompileSuccess(datatype([
    ('project_name_classes_dir_mapping', tuple),
]), BloopHackyProtocol):

  @classmethod
  def parse_from_json(cls, json_obj):
    return cls(tuple(json_obj.items()))


class BloopCompileError(datatype([
    ('failed_project_names', string_list),
]), BloopHackyProtocol):

  @classmethod
  def parse_from_json(cls, json_obj):
    return cls(json_obj)


class PantsCompileRequest(datatype([
    ('sources', string_list),
]), BloopHackyProtocol):

  @classmethod
  def parse_from_json(cls, json_obj):
    return cls(json_obj)


class BloopLauncherMessage(enum_struct({
    'bloop-compile-success': BloopCompileSuccess,
    'bloop-compile-error': BloopCompileError,
    'pants-compile-request': PantsCompileRequest,
})):

  @classmethod
  def parse_json_string(cls, json_line):
    """???/creates a message object from json

    ???/json messages are expected to be valid json, containing exactly the keys 'message_type' and
    'contents'
    """
    msg = json.loads(json_line)
    tag = msg['message_type']
    msg_cls = cls.type_mapping[tag]
    msg_contents = msg['contents']
    msg_obj = msg_cls.parse_from_json(msg_contents)
    return cls(tag=tag, value=msg_obj)


class BloopInvocationRequest(datatype([
    ('bsp_launcher_process', SubclassesOf(ProcessHandler)),
])): pass


class BloopInvocationResult(enum_struct({
    'success': BloopCompileSuccess,
    'failure': BloopCompileError,
})): pass


# TODO: merge this with `BloopLauncherMessage`?!
@union
class BloopLauncherMessageTag(object): pass


class BloopIntermediateResult(enum_struct({
    'keep-going': type(None),
    'done': BloopInvocationResult,
})): pass


@rule(BloopIntermediateResult, [BloopCompileSuccess])
def process_bloop_success(bloop_compile_success):
  return BloopIntermediateResult(BloopInvocationResult(bloop_compile_success))


@rule(BloopIntermediateResult, [BloopCompileError])
def process_bloop_error(bloop_compile_error):
  return BloopIntermediateResult(BloopInvocationResult(bloop_compile_error))


@rule(BloopIntermediateResult, [PantsCompileRequest])
def process_pants_compile_request(pants_compile_request):
  raise NotImplementedError(f'oops! {pants_compile_request}')
  return BloopIntermediateResult(None)


@rule(BloopInvocationResult, [BloopInvocationRequest])
def invoke_bloop(bloop_invocation_request):
  for line in bloop_invocation_request.bsp_launcher_process.stdout:
    msg = BloopLauncherMessage.parse_json_string(line.decode('utf-8'))
    maybe_result = yield Get(BloopIntermediateResult, BloopLauncherMessageTag, msg.value)
    # TODO: figure out how to do functional pattern matching with `yield` expressions!
    do_quit = maybe_result.match({
      'keep-going': lambda _: False,
      'done': lambda _: True,
    })
    if do_quit:
      yield maybe_result.value

  raise Exception("shouldn't get here!!")


class BloopCompile(NailgunTask):

  @classmethod
  def register_options(cls, register):
    super(BloopCompile, cls).register_options(register)

    cls.register_jvm_tool(
      register,
      'bloop-compile-wrapper',
      classpath=[
        JarDependency(
          org='org.pantsbuild',
          name='bloop-compile-wrapper_2.12',
          rev='???',
        ),
      ],
    )

  @classmethod
  def prepare(cls, options, round_manager):
    super(BloopCompile, cls).prepare(options, round_manager)
    round_manager.require_data('bloop_classes_dir')

  _supported_languages = ['java', 'scala']

  _confs = Zinc.DEFAULT_CONFS

  def execute(self):
    jvm_targets = self.get_targets(lambda t: isinstance(t, JvmTarget))

    bsp_launcher_process = self.runjava(
      classpath=self.tool_classpath('bloop-compile-wrapper'),
      main='pants.contrib.bloop.compile.PantsCompileMain',
      jvm_options=[],
      # TODO: jvm options need to be prefixed with -J and passed to the LauncherMain if we want to
      # use them!
      args=[
        # FIXME: just pipe in the "level" option! This is a hack for easier debugging!
        'debug', # self.get_options().level,
        '--',
      ] + [t.id for t in jvm_targets],
      workunit_name='bloop-compile',
      workunit_labels=[WorkUnitLabel.COMPILER],
      do_async=True,
      # stdin=subprocess.PIPE,
      stdin=None,
      stdout=subprocess.PIPE,
    )

    bloop_invocation_result, = self.context._scheduler.product_request(BloopInvocationResult, [
      BloopInvocationRequest(bsp_launcher_process=bsp_launcher_process),
    ])

    # bsp_launcher_process.stdin.close()
    bsp_launcher_process.stdout.close()
    bsp_launcher_process.wait()
    rc = bsp_launcher_process.wait()
    if rc != 0:
      raise TaskError('???', exit_code=rc)

    target_name_to_classes_dir = dict(bloop_invocation_result.value.project_name_classes_dir_mapping)

    self.context.log.info('target_name_to_classes_dir: {}'.format(target_name_to_classes_dir))

    for target in jvm_targets:
      classes_dir = self.context.products.get_data('bloop_classes_dir').get(target, None)
      if classes_dir:
        bloop_internal_classes_dir = target_name_to_classes_dir.get(target.id, None)
        if bloop_internal_classes_dir is not None:
          new_cp_entry = ClasspathEntry(bloop_internal_classes_dir)
          self.context.products.get_data('runtime_classpath').add_for_target(
            target,
            [(conf, new_cp_entry) for conf in self._confs])

    self.context.log.info('finished compile!')


def rules():
  return [
    process_bloop_success,
    UnionRule(BloopLauncherMessageTag, BloopCompileSuccess),
    process_bloop_error,
    UnionRule(BloopLauncherMessageTag, BloopCompileError),
    process_pants_compile_request,
    UnionRule(BloopLauncherMessageTag, PantsCompileRequest),
    invoke_bloop,
    RootRule(BloopInvocationRequest),
  ]
