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
from pants.util.memo import memoized_classmethod
from pants.util.meta import AbstractClass
from pants.util.objects import Exactly, SubclassesOf, datatype, enum, string_list
from pants.util.process_handler import ProcessHandler, subprocess


# TODO: make the enum keyed off of `type`s directly?
class BloopLauncherMessageType(enum([
    'bloop-compile-success',
    'bloop-compile-error',
    'pants-compile-request',
])): pass


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


class BloopLauncherMessage(datatype([
    ('message_type', BloopLauncherMessageType),
    ('contents', Exactly(BloopCompileSuccess, BloopCompileError, PantsCompileRequest)),
])):

  @memoized_classmethod
  def _message_class(cls, msg_type):
    """???"""
    return msg_type.resolve_for_enum_variant({
      'bloop-compile-success': BloopCompileSuccess,
      'bloop-compile-error': BloopCompileError,
      'pants-compile-request': PantsCompileRequest,
    })

  @classmethod
  def parse_json_string(cls, json_line):
    """???/creates a message object from json

    ???/json messages are expected to be valid json, containing exactly the keys 'message_type' and
    'contents'
    """
    msg = json.loads(json_line)
    msg_type = BloopLauncherMessageType(msg['message_type'])
    msg_cls = cls._message_class(msg_type)
    msg_contents = msg['contents']
    msg_obj = msg_cls.parse_from_json(msg_contents)
    return cls(message_type=msg_type, contents=msg_obj)


class BloopInvocationRequest(datatype([
    ('bsp_launcher_process', SubclassesOf(ProcessHandler)),
])): pass


class BloopInvocationResult(datatype([
    # FIXME: flesh out the enum pattern more here! this is an Either[Error, Success], basically
    ('project_name_classes_dir_mapping', Exactly(tuple, type(None))),
    ('failed_project_names', Exactly(list, type(None))),
])):

  def __new__(cls, *, project_name_classes_dir_mapping=None, failed_project_names=None):
    # TODO: make an xor function?
    assert (project_name_classes_dir_mapping is not None) or (failed_project_names is not None)
    assert (project_name_classes_dir_mapping is None) or (failed_project_names is None)
    return super().__new__(cls,
                           project_name_classes_dir_mapping=project_name_classes_dir_mapping,
                           failed_project_names=failed_project_names)


# TODO: merge this with `BloopLauncherMessage`?!
@union
class BloopLauncherMessageTag(object): pass


class BloopIntermediateResult(datatype([
    # FIXME: flesh out the enum pattern more here! None => no final result, keep going!
    ('actual_result', Exactly(BloopInvocationResult, type(None))),
])): pass


@rule(BloopIntermediateResult, [BloopCompileSuccess])
def process_bloop_success(bloop_compile_success):
  return BloopIntermediateResult(BloopInvocationResult(
    project_name_classes_dir_mapping=bloop_compile_success.project_name_classes_dir_mapping))


@rule(BloopIntermediateResult, [BloopCompileError])
def process_bloop_error(bloop_compile_error):
  return BloopIntermediateResult(BloopInvocationResult(
    failed_project_names=bloop_compile_error.failed_project_names))


@rule(BloopIntermediateResult, [PantsCompileRequest])
def process_pants_compile_request(pants_compile_request):
  raise NotImplementedError(f'oops! {pants_compile_request}')
  return BloopIntermediateResult(actual_result=None)


@rule(BloopInvocationResult, [BloopInvocationRequest])
def invoke_bloop(bloop_invocation_request):
  for line in bloop_invocation_request.bsp_launcher_process.stdout:
    msg = BloopLauncherMessage.parse_json_string(line.decode('utf-8'))
    maybe_result = yield Get(BloopIntermediateResult, BloopLauncherMessageTag, msg.contents)
    if maybe_result.actual_result is not None:
      yield maybe_result.actual_result

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

    assert bloop_invocation_result.failed_project_names is None
    target_name_to_classes_dir = dict(bloop_invocation_result.project_name_classes_dir_mapping)

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
