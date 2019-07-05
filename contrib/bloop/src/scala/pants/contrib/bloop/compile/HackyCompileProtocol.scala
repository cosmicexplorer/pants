package pants.contrib.bloop.compile

import ammonite.ops._
import spray.json._

import DefaultJsonProtocol._

// Implement the protocol described via v2 `@rule`s in bloop_compile.py!!
// NB: This is a "hacky" protocol for a reason -- we should just be communicating with bloop
// directly (bidirectionally) via BSP!!!

sealed trait BloopLauncherParsedMessage {
  def intoMessage: BloopLauncherMessage
}
case class BloopCompileSuccess(targetClassesDirMapping: Map[String, Path])
    extends BloopLauncherParsedMessage {
  override def intoMessage: BloopLauncherMessage = BloopLauncherMessage(
    messageType = "bloop-compile-success",
    contents = targetClassesDirMapping.map { case (k, v) => (k -> v.toString) }.toJson)
}
case class BloopCompileError(failedProjectNames: Seq[String])
  extends BloopLauncherParsedMessage {
  override def intoMessage: BloopLauncherMessage = BloopLauncherMessage(
    messageType = "bloop-compile-error",
    contents = failedProjectNames.toJson)
}
case class PantsCompileRequest(sources: Seq[String]) extends BloopLauncherParsedMessage {
  override def intoMessage: BloopLauncherMessage = BloopLauncherMessage(
    messageType = "pants-compile-request",
    contents = sources.toJson)
}

object BloopHackyProtocol extends DefaultJsonProtocol {
  implicit val hackyFormat = jsonFormat(BloopLauncherMessage, "message_type", "contents")
}
case class BloopLauncherMessage(messageType: String, contents: JsValue) {
  import BloopHackyProtocol._
  def asSprayJson = this.toJson
}
