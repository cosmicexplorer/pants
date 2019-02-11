// From https://github.com/graalvm/graalvm-demos/tree/master/scala-days-2018/scalac-native!
package scala.tools.nsc.substitutions

final class Target_scala_tools_nsc_ast_TreeBrowsers$SwingBrowser {
  def browse(pName: String, units: List[AnyRef]): Unit = {
    throw new RuntimeException("Swing currently unsupported in the native compiler.")
  }
}
