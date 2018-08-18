# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=globs('test_*.py', exclude=([globs('*_integration.py')])),
  dependencies=[
    '3rdparty/python:future',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/native',
    'src/python/pants/backend/native/targets',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'standalone/python_dist/src/python/pants/standalone/pthon_dist/targets',
    'standalone/python_dist/src/python/pants/standalone/pthon_dist/tasks',
    'standalone/python_dist/tests/python/pants_test/standalone/python_dist/tasks/util',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/engine:scheduler_test_base',
  ],
  tags={'platform_specific_behavior'},
)

python_tests(
  name='integration',
  sources=globs('*_integration.py'),
  dependencies=[
    '3rdparty/python:future',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/native',
    'src/python/pants/backend/native/targets',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/backend/python/tasks/util',
    'tests/python/pants_test/engine:scheduler_test_base',
  ],
  tags={'platform_specific_behavior', 'integration'},
  timeout=2400,
)
