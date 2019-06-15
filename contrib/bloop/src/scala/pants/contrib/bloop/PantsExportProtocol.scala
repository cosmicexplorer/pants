package pants.contrib.bloop

import spray.json._

case class SourceRoot(sourceRootPath: String, packagePrefix: String)

case class Target(
  dependencies: Seq[String],
  targetType: String,
  scope: String,
  roots: Seq[SourceRoot],
  isTargetRoot: Boolean,
  specPath: String,
  main: Option[String],
  excludes: Option[Seq[String]],
  id: String,
  sources: Option[Seq[String]],
  libraries: Seq[String],
  transitive: Boolean,
  isCodeGen: Boolean,
  platform: Option[String],
  isSynthetic: Boolean,
  classesDir: Option[String],
  zincAnalysis: Option[String],
  zincArgs: Option[Seq[String]])

case class JvmPlatform(sourceLevel: String, args: Seq[String], targetLevel: String)

case class JvmPlatformDict(platforms: Map[String, JvmPlatform], defaultPlatform: String)

case class PreferredJvmDistribution(strict: Option[String], nonStrict: String)

case class PantsExport(
  targets: Map[String, Target],
  jvmPlatforms: JvmPlatformDict,
  preferredJvmDistributions: Map[String, PreferredJvmDistribution],
  version: String,
  libraries: Map[String, Map[String, String]])

object PantsExportProtocol extends DefaultJsonProtocol {
  implicit val sourceRootFormat = jsonFormat(SourceRoot, "source_root", "package_prefix")
  implicit val targetFormat = jsonFormat(
    Target,
    "targets", "pants_target_type", "scope", "roots", "is_target_root", "spec_path", "main",
    "excludes", "id", "sources", "libraries", "transitive", "is_code_gen", "platform",
    "is_synthetic", "classes_dir", "zinc_analysis", "zinc_args")
  implicit val jvmPlatformFormat = jsonFormat(JvmPlatform, "source_level", "args", "target_level")
  implicit val jvmPlatformDictFormat = jsonFormat(JvmPlatformDict, "platforms", "default_platform")
  implicit val preferredJvmDistFormat = jsonFormat(PreferredJvmDistribution, "strict", "non_strict")
  implicit val pantsExportFormat = jsonFormat(
    PantsExport, "targets", "jvm_platforms", "preferred_jvm_distributions", "version", "libraries")
}
