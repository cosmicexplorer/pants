package org.pantsbuild.example.build_graph

import spray.json._

import scala.io.Source


case class Digest(
  fingerprint: String,
  serialized_bytes_length: Int,
)

case class PantsListOutput(
  was_root: Boolean,
  address: String,
  dependencies: Seq[String],
  sources_digest: Option[Digest],
  type_alias: String,
  intransitive_fingerprint: String,
  transitive_fingerprint: String,
)

object PantsListProtocol extends DefaultJsonProtocol {
  implicit val digestFormat = jsonFormat2(Digest)
  implicit val pantsListOutputFormat = jsonFormat7(PantsListOutput)
}


case class TargetAddress(spec: String)


case class DependencyAddress(spec: String)


object Main extends App {
  import PantsListProtocol._

  val parsedPantsOutput: Map[TargetAddress, Seq[DependencyAddress]] = Source.stdin.getLines
    .map(_.parseJson.convertTo[PantsListOutput])
    .map(parsed => (TargetAddress(parsed.address) -> parsed.dependencies.map(DependencyAddress)))
    .toMap

  val allDeps: Set[DependencyAddress] = parsedPantsOutput.flatMap(_._2).toSet
  val locallyOrphanedTargets: Seq[TargetAddress] = parsedPantsOutput.keys
    .flatMap {
      case TargetAddress(spec) => {
        val asDependency = DependencyAddress(spec)
        if (allDeps.contains(asDependency)) {
          None
        } else {
          Some(TargetAddress(spec))
        }
      }
    }.toSeq

  val numOrphaned = locallyOrphanedTargets.length
  val numTotal = parsedPantsOutput.keys.toSeq.length
  System.err.println(s"$numOrphaned locally orphaned targets detected (out of $numTotal)")
  locallyOrphanedTargets.foreach(t => println(t.spec))
}
