# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_requirements()

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
)
