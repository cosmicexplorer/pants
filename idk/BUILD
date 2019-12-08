python_binary(
  name='dehydrated',
  source='main.py',
)

python_binary(
  name='wrapped',
  source='real-main.py',
  dependencies=[
    ':resources',
  ],
)

python_library(
  name='resources',
  sources=[
    'main.py',
    'IPEX-INFO',
    'PTEX-INFO',
  ],
)
