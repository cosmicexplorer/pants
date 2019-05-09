# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# see/edit requirements.txt in this directory to change deps.
python_requirements()

# NB: google-cloud-bigquery has the following prelude upon import:
#
# from pkg_resources import get_distribution
# __version__ == get_distribution("google-cloud-bigquery").version
#
# which will fail at import time with pkg_resources.DistributionNotFound.
# The argument `prepend_to_pythonpath=True` will work around this particular error by ensuring the
# requirements are within a pex file located at the at the front of the PEX_PATH when executing
# pytest. Note that even though this works, it will still show the following warning:
#
# pex/environment.py:330: PEXWarning: The `pkg_resources` package was loaded from a pex vendored
# version when declaring namespace packages defined by google-cloud-bigquery 1.10.0. The
# google-cloud-bigquery 1.10.0 distribution should fix its `install_requires` to include
# `setuptools`.
python_requirement_library(
  name='google-cloud-bigquery',
  requirements=[
    python_requirement('google-cloud-bigquery==1.10.0'),
  ],
  # TODO: The `prepend_to_pythonpath` hack seems to invalidate some assumptions that pants makes in
  # creating the pytest pex. In this case, it seems to require the `requests` module early at import
  # time, as was observed in the stack trace. If an error appears at module import time like this,
  # adding a dependency to the module that shows up in the import stack trace should resolve the
  # error.
  dependencies=[
    '3rdparty/python:requests',
  ],
  prepend_to_pythonpath=True,
)

remote_sources(
  name='tensorflow-framework',
  dest=packaged_native_library,
  sources_target=':tensorflow-native-libs',
  args=dict(
    include_relpath='include',
    lib_relpath='',
    native_lib_names=['tensorflow_framework'],
  ),
)

unpacked_whls(
  name='tensorflow-native-libs',
  libraries=[':tensorflow'],
  module_name='tensorflow',
  include_patterns=[
    'include/**/*',
    './*.so',
  ],
  within_data_subdir='purelib/tensorflow',
)
