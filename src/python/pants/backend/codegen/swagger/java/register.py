# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.swagger.java.java_swagger_library import JavaSwaggerLibrary
from pants.backend.codegen.swagger.java.swagger_gen import SwaggerGen
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'java_swagger_library': JavaSwaggerLibrary,
    }
  )


def register_goals():
  task(name='swagger', action=SwaggerGen).install('gen')
