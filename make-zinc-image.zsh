#!/usr/bin/env zsh

set -euxo pipefail

export SCALA_HOME=/usr/local/Cellar/scala/2.12.3
export SCALA_LIB_HOME="${SCALA_HOME}/libexec"
export GRAALVM_HOME="${HOME}/.cache/pants/bin/graal/mac/10.13/1.0.0-rc13/graal/graalvm-ce-1.0.0-rc13/Contents/Home"
export JAVA_HOME=/Users/dmcclanahan/Downloads/openjdk1.8.0_202-jvmci-0.56/Contents/home

./pants binary src/scala/org/pantsbuild/zinc/compiler:bin

~/tools/mx/mx \
  -p ~/tools/graal/substratevm native-image \
  -cp dist/bin.jar:$SCALA_LIB_HOME/lib/scala-compiler.jar:$SCALA_LIB_HOME/lib/scala-library.jar:$SCALA_LIB_HOME/lib/scala-reflect.jar:${HOME}/tools/graalvm-demos/scala-days-2018/scalac-native/scalac-substitutions/target/scala-2.12/scalac-substitutions_2.12-0.1.0-SNAPSHOT.jar \
  -H:SubstitutionResources=substitutions.json,substitutions-2.12.json \
  -H:ReflectionConfigurationFiles=${HOME}/tools/graalvm-demos/scala-days-2018/scalac-native/scalac-substitutions/reflection-config.json \
  org.pantsbuild.zinc.compiler.Main \
  --verbose --no-server \
  --enable-all-security-services --allow-incomplete-classpath \
  -O0 -J-Xmx8g \
  --report-unsupported-elements-at-runtime \
  -H:+ReportExceptionStackTraces \
  --delay-class-initialization-to-runtime=org.pantsbuild.zinc.compiler.Main \
  --delay-class-initialization-to-runtime='org.pantsbuild.zinc.compiler.Main$' \
  --delay-class-initialization-to-runtime=scala.tools.nsc.interpreter.IMain \
  --delay-class-initialization-to-runtime='scala.tools.nsc.interpreter.IMain$' \
  --delay-class-initialization-to-runtime=scala.tools.nsc.interpreter.NamedParam \
  --delay-class-initialization-to-runtime=sbt.internal.util.StringTypeTag \
  --delay-class-initialization-to-runtime=org.pantsbuild.zinc.compiler.InputUtils \
  --delay-class-initialization-to-runtime='scala.tools.nsc.interpreter.IBindings' \
  --delay-class-initialization-to-runtime='scala.reflect.runtime.package$' \
  --delay-class-initialization-to-runtime='scala.tools.nsc.interpreter.StdReplTags$'

# -H:NumberOfThreads=1 \

./org.pantsbuild.zinc.compiler.main -help

./pants clean-all

./pants -ldebug compile.zinc --execution-strategy=subprocess src/scala/org/pantsbuild/zinc/compiler
