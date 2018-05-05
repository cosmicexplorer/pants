# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from abc import abstractmethod

from pants.binaries.binary_util import BinaryUtilPrivate
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property
from pants.util.osutil import OsId


logger = logging.getLogger(__name__)


# TODO(cosmicexplorer): Add integration tests for this file.
class BinaryToolBase(Subsystem):
  """Base class for subsytems that configure binary tools.

  Subclasses can be further subclassed, manually, e.g., to add any extra options.

  :API: public
  """
  # Subclasses must set these to appropriate values for the tool they define.
  # They must also set options_scope appropriately.
  platform_dependent = None
  archive_type = None  # See pants.fs.archive.archive for valid string values.
  default_version = None

  # Subclasses may set this to the tool name as understood by BinaryUtil.
  # If unset, it defaults to the value of options_scope.
  name = None

  # Subclasses may set this to a suffix (e.g., '.pex') to add to the computed remote path.
  # Note that setting archive_type will add an appropriate archive suffix after this suffix.
  suffix = ''

  # Subclasses may set these to effect migration from an old --version option to this one.
  # TODO(benjy): Remove these after migration to the mixin is complete.
  replaces_scope = None
  replaces_name = None

  # Subclasses may set this to provide extra register() kwargs for the --version option.
  extra_version_option_kwargs = None

  # TODO: ???
  dist_url_versions = []

  @classmethod
  def subsystem_dependencies(cls):
    return super(BinaryToolBase, cls).subsystem_dependencies() + (BinaryUtilPrivate.Factory,)

  @classmethod
  @abstractmethod
  def make_dist_urls(cls, version, os_name):
    """???/Generate a default value for this subsystem's --urls option."""

  @classmethod
  def _os_id(cls):
    return OsId.for_current_platform()

  @classmethod
  def _default_urls(cls):
    os_id = cls._os_id()
    return {
      version: cls.make_dist_urls(version, os_id.os_name)
      for version in cls.dist_url_versions
    }

  @classmethod
  def register_options(cls, register):
    super(BinaryToolBase, cls).register_options(register)

    cls_name = cls._get_name()
    binary_description = 'binary' if cls.platform_dependent else 'script'

    version_registration_kwargs = {
      'type': str,
      'default': cls.default_version,
    }
    if cls.extra_version_option_kwargs:
      version_registration_kwargs.update(cls.extra_version_option_kwargs)
    version_registration_kwargs['help'] = (
      version_registration_kwargs.get('help') or
      'Version of the {} {} to use'.format(cls_name, binary_description)
    )
    # The default for fingerprint in register() is False, but we want to default to True.
    if 'fingerprint' not in version_registration_kwargs:
      version_registration_kwargs['fingerprint'] = True

    register('--version', **version_registration_kwargs)

    register('--urls', type=dict, default=cls._default_urls(), help=(
      "Dict of (version -> [URL]) to fetch the {} {} from. If no URLs were provided for the "
      "selected version, pants will fetch the tool from a URL under --binaries-baseurls."
      .format(cls_name, binary_description)))

  @memoized_method
  def select(self, context=None):
    """Returns the path to the specified binary tool.

    If replaces_scope and replaces_name are defined, then the caller must pass in
    a context, otherwise no context should be passed.

    # TODO: Once we're migrated, get rid of the context arg.

    :API: public
    """
    return self._select_for_version(self.version(context))

  @memoized_method
  def version(self, context=None):
    """Returns the version of the specified binary tool.

    If replaces_scope and replaces_name are defined, then the caller must pass in
    a context, otherwise no context should be passed.

    # TODO: Once we're migrated, get rid of the context arg.

    :API: public
    """
    if self.replaces_scope and self.replaces_name:
      if context:
        # If the old option is provided explicitly, let it take precedence.
        old_opts = context.options.for_scope(self.replaces_scope)
        if old_opts.get(self.replaces_name) and not old_opts.is_default(self.replaces_name):
          return old_opts.get(self.replaces_name)
      else:
        logger.warn('Cannot resolve version of {} from deprecated option {} in scope {} without a '
                    'context!'.format(self._get_name(), self.replaces_name, self.replaces_scope))
    return self.get_options().version

  @memoized_property
  def _binary_util(self):
    return BinaryUtilPrivate.Factory.create()

  @classmethod
  def get_support_dir(cls):
    return 'bin/{}'.format(cls._get_name())

  def _select_for_version(self, version):
    return self._binary_util.select(
      supportdir=self.get_support_dir(),
      version=version,
      name='{}{}'.format(self._get_name(), self.suffix),
      platform_dependent=self.platform_dependent,
      archive_type=self.archive_type,
      urls=self.get_options().urls.get(version, None))

  @classmethod
  def _get_name(cls):
    return cls.name or cls.options_scope


class NativeTool(BinaryToolBase):
  """A base class for native-code tools.

  :API: public
  """
  platform_dependent = True


class Script(BinaryToolBase):
  """A base class for platform-independent scripts.

  :API: public
  """
  platform_dependent = False


class ExecutablePathProvider(object):
  """Mixin for subsystems which provide directories containing executables.

  This is useful to abstract over different sources of executables
  (e.g. BinaryTool archives or files from the host filesystem), or for
  aggregating multiple such subsystems.
  """

  def path_entries(self):
    return []
