# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(
  name='bin',
  basename='native-image-stubs',
  dependencies=[
    ':native-image-stubs',
  ],
)

# From https://github.com/graalvm/graalvm-demos/tree/master/scala-days-2018/scalac-native! Required
# to build a graal native-image of scalac -- registered as the //:native-image-stubs by
# ScalacCompile!
scala_library(
  provides=scala_artifact(
    org='org.pantsbuild',
    name='native-image-stubs',
    repo=public,
    publication_metadata=pants_library('Reflection configs and class stubs for graal native-image'),
  ),
  dependencies=[
    ':substitutions-in-java',
    ':substitution-configs',
  ],
  # NB: This is the default glob, but it's good to be explicit with multiple target types in the
  # same directory.
  sources=globs('*.scala'),
)

# TODO: If this is just here to show that you can write substitutions in Java, note that!
java_library(
  name='substitutions-in-java',
  # NB: This is the default glob, but it's good to be explicit with multiple target types in the
  # same directory.
  sources=globs('*.java'),
)

resources(
  name='substitution-configs',
  sources=globs('*.json'),
)
