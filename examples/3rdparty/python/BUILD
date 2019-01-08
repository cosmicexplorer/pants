# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_requirements()

native_python_wheel(
  name='tensorflow-framework',
  include_relpath='include/',
  lib_relpath='',
  module_name='tensorflow',
  native_lib_names=['tensorflow_framework'],
  requirement_target_spec=':tensorflow',
)
