# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.binaries.binary_tool import NativeTool


class Swagger(NativeTool):
  options_scope = 'swagger'
  default_version = '0.21.0'
  replaces_name = 'version'
