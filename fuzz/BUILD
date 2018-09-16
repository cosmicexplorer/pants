python_requirement_library(
  name='afl',
  requirements=[
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
  sources=['main.py'],
  entry_point='main:main',
  dependencies=[
    ':afl',
    ':fuzz',
    'src/python/pants/base:exiter',
    'src/python/pants/bin',
    'src/python/pants/util:contextutil',
  ],
)
