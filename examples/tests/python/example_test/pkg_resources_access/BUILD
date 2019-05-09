# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  dependencies=[
    'tests/python/pants_test:int-test',
    'examples/3rdparty/python:google-cloud-bigquery',
  ],
)

python_binary(
  name='bin',
  source='main.py',
  dependencies=[
    'examples/3rdparty/python:google-cloud-bigquery',
  ],
)
