# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Test the Hello World example's "greet" library

# junit-3rdparty-example
junit_tests(
  sources=['GreetingTest.java'],
  dependencies=[
    # use the jar_library(name = 'junit', ...) declared in 3rdparty/BUILD
    '3rdparty:junit',
    'examples/src/java/org/pantsbuild/example/hello/greet',
    'examples/src/resources/org/pantsbuild/example/hello',
  ],
)
# end-junit-3rdparty-example
