# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import shutil

from future.utils import text_type

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.base.build_environment import get_pants_cachedir
from pants.base.hash_utils import stable_json_hash
from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir_for
from pants.util.memo import memoized_method, memoized_property
from pants.util.process_handler import subprocess
from pants.util.strutil import safe_shlex_join


logger = logging.getLogger(__name__)


class GraalCEUrlGenerator(BinaryToolUrlGenerator):

  _DIST_URL_FMT = 'https://github.com/oracle/graal/releases/download/vm-{version}/{base}'
  _ARCHIVE_BASE_FMT = 'graalvm-ce-{version}-{system_id}-amd64.tar.gz'
  _SYSTEM_ID = {
    'mac': 'macos',
    'linux': 'linux',
  }

  def generate_urls(self, version, host_platform):
    system_id = self._SYSTEM_ID[host_platform.os_name]
    archive_basename = self._ARCHIVE_BASE_FMT.format(version=version, system_id=system_id)
    return [self._DIST_URL_FMT.format(version=version, base=archive_basename)]


class GraalCE(NativeTool, JvmToolMixin):

  options_scope = 'graal'
  default_version = '1.0.0-rc9'
  archive_type = 'tgz'

  def get_external_url_generator(self):
    return GraalCEUrlGenerator()

  @classmethod
  def register_options(cls, register):
    super(GraalCE, cls).register_options(register)
    register('--report-unsupported-elements', type=bool, default=True, fingerprint=True,
             advanced=True,
             # TODO: this is plagiarized directly from `native-image --help`!
             help='Whether to report usage of unsupported methods and fields at run time when '
                  'accessed for the first time, instead of as an error during image building.')

  @memoized_property
  def _report_unsupported_elements(self):
    return self.get_options().report_unsupported_elements

  _FINAL_PATH_COMPONENTS = {
    'mac': ['Contents', 'home'],
    'linux': [],
  }

  @memoized_method
  def select(self):
    unpacked_base_path = super(GraalCE, self).select()
    return os.path.join(
      unpacked_base_path,
      'graalvm-ce-{}'.format(self.version()),
      *self._FINAL_PATH_COMPONENTS[self.host_platform.os_name])

  @memoized_property
  def bin_dir(self):
    return os.path.join(self.select(), 'bin')

  @memoized_property
  def _native_image_exe(self):
    return os.path.join(self.bin_dir, 'native-image')

  @memoized_property
  def _cache_dir(self):
    return os.path.join(get_pants_cachedir(), 'graal-images')

  class NativeImageCreationError(Exception): pass

  def produce_native_image(self, tool_classpath, main_class, input_fingerprint):
    if not isinstance(input_fingerprint, text_type):
      raise self.NativeImageCreationError(
        "Input fingerprint provided must be an instance of {}: was {!r} (type {}). "
        "JVM tools using the 'graal' execution_strategy must provide an 'input_fingerprint' "
        "argument to self.runjava()."
        .format(text_type.__name__, input_fingerprint, type(input_fingerprint).__name__))

    # We have finished with the digest.
    input_hash = stable_json_hash([input_fingerprint, self._report_unsupported_elements])
    output_image_file_name = '{}-{}'.format(main_class, input_hash)

    fingerprinted_native_image_path = os.path.join(self._cache_dir, output_image_file_name)
    if os.path.isfile(fingerprinted_native_image_path):
      return fingerprinted_native_image_path

    cp_formatted = ':'.join(tool_classpath)
    argv = [
      self._native_image_exe,
      '-cp', cp_formatted,
      main_class,
    ]
    if self._report_unsupported_elements:
      argv.append('--report-unsupported-elements-at-runtime')

    pprinted_argv = safe_shlex_join(argv)
    with temporary_dir() as tmp_dir:
      image_output_path = os.path.join(tmp_dir, main_class)

      logger.info('Building graal native image for {}...'.format(main_class))
      rc = subprocess.check_call(argv, cwd=tmp_dir)
      if rc != 0:
        raise self.NativeImageCreationError(
          "Error creating graal native image with cmd '{}': exited with {}."
          .format(pprinted_argv, rc))
      elif os.path.isfile(image_output_path):
        safe_mkdir_for(fingerprinted_native_image_path)
        shutil.move(image_output_path, fingerprinted_native_image_path)
        logger.info('Graal native image built at {}.'.format(fingerprinted_native_image_path))
        return fingerprinted_native_image_path
      else:
        raise self.NativeImageCreationError(
          "Error creating graal native image with cmd '{}': file '{}' not found."
          .format(pprinted_argv, image_output_path))
