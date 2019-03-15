#!/usr/bin/env zsh

set -euxo pipefail

export SCALA_HOME='/usr/share/scala'
export SCALA_LIB_HOME="${SCALA_HOME}"
export GRAALVM_HOME="${HOME}/.cache/pants/bin/graal/linux/x86_64/1.0.0-rc13/graal/graalvm-ce-1.0.0-rc13"
export JAVA_HOME="${HOME}/Downloads/openjdk1.8.0_202-jvmci-0.56"

./pants binary src/scala/org/pantsbuild/zinc/compiler:bin

~/tools/mx/mx \
  -p ~/tools/graal/substratevm native-image \
  -cp dist/bin.jar:$SCALA_LIB_HOME/lib/scala-compiler.jar:$SCALA_LIB_HOME/lib/scala-library.jar:$SCALA_LIB_HOME/lib/scala-reflect.jar:${HOME}/tools/graalvm-demos/scala-days-2018/scalac-native/scalac-substitutions/target/scala-2.12/scalac-substitutions_2.12-0.1.0-SNAPSHOT.jar \
  -H:SubstitutionResources=substitutions.json,substitutions-2.12.json \
  -H:ReflectionConfigurationFiles=${HOME}/tools/graalvm-demos/scala-days-2018/scalac-native/scalac-substitutions/reflection-config.json \
  -H:ConfigurationFileDirectories="$(pwd)/native-image-configure/" \
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
  --delay-class-initialization-to-runtime='scala.tools.nsc.interpreter.StdReplTags$' \
  -H:NumberOfThreads=1

## removed from generated reflect-config.json (unrecognized):
# {
#   "name":"com.sun.tools.javadoc.Main"
# },
# {
#   "name":"org.graalvm.compiler.hotspot.nodes.ObjectWriteBarrier",
#   "allDeclaredFields":true
# },
# {
#   "name":"org.graalvm.compiler.hotspot.nodes.SerialWriteBarrier",
#   "allDeclaredFields":true
# },
## removed from generated reflect-config.json (causing errors):
# {
#   "name":"org.graalvm.compiler.hotspot.replacements.ObjectSubstitutions",
#   "allDeclaredMethods":true
# },
# {
#   "name":"org.graalvm.compiler.hotspot.replacements.ThreadSubstitutions",
#   "allDeclaredMethods":true
# },
# {
#   "name":"org.graalvm.compiler.hotspot.replacements.ClassGetHubNode"
# },
# {
#   "name":"org.graalvm.compiler.hotspot.replacements.ReflectionSubstitutions",
#   "allDeclaredMethods":true
# },
# {
#   "name":"org.graalvm.compiler.hotspot.replacements.HotSpotClassSubstitutions",
#   "allDeclaredMethods":true
# },
# {
#   "name":"org.graalvm.compiler.hotspot.replacements.HotSpotReplacementsUtil"
# },
# {
#   "name":"org.graalvm.compiler.replacements.nodes.ArrayRegionEqualsNode"
# },
# {
#   "name":"org.graalvm.compiler.hotspot.replacements.HotSpotArraySubstitutions",
#   "allDeclaredMethods":true
# },
# {
#   "name":"org.graalvm.compiler.replacements.amd64.AMD64StringSubstitutions",
#   "allDeclaredMethods":true
# },


./org.pantsbuild.zinc.compiler.main -help

./pants clean-all

./pants -ldebug compile.zinc --execution-strategy=subprocess src/scala/org/pantsbuild/zinc/compiler
