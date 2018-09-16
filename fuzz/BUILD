python_requirement_library(
  name='afl',
  requirements=[
    python_requirement('Cython>=0.19'),
    python_requirement('python-afl==0.7.1'),
  ],
)

python_library(
  dependencies=[
    'src/python/pants/util:contextutil',
  ],
)

python_binary(
  name='bin',
  source='main.py',
  dependencies=[
    ':afl',
    ':fuzz',
    'src/python/pants/base:exiter',
    'src/python/pants/bin',
    'src/python/pants/util:process_handler',
  ],
)
