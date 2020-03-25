scala_library(
  dependencies=[
    'examples/3rdparty/jvm:spray-json',
  ],
)

jvm_binary(
  name='find-orphaned-targets',
  main='org.pantsbuild.example.build_graph.Main',
  dependencies=[
    ':build_graph',
  ],
)
