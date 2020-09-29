package pants.contrib.bloop.compile

import ammonite.ops._
import bloop.bsp.BloopLanguageClient
import bloop.bsp.BloopLanguageServer
import bloop.internal.build.BuildInfo
import bloop.launcher.LauncherMain
import bloop.launcher.core.{Installer, Shell}
import bloop.launcher.util.Environment
import bloop.logging.BspClientLogger
import bloop.logging.DebugFilter
import bloop.logging.Logger
import ch.epfl.scala.bsp
import ch.epfl.scala.bsp.endpoints
import io.circe._
import io.circe.derivation.JsonCodec
import io.circe.parser._
import io.circe.syntax._
import monix.eval.Task
import monix.execution.Ack
import monix.execution.ExecutionModel
import monix.execution.Scheduler
import monix.reactive.{Consumer, Observable}
import sbt.internal.util.{BasicLogger, ConsoleLogger, ConsoleOut, StackTrace}
import sbt.util.{ControlEvent, Level, LogEvent}

import scala.concurrent.Await
import scala.concurrent.duration.FiniteDuration
import scala.concurrent.ExecutionContext.Implicits.global
import scala.concurrent.Promise
import scala.io.Source
import scala.meta.jsonrpc._

import java.io.PipedInputStream
import java.io.PipedOutputStream
import java.nio.charset.StandardCharsets
import java.util.concurrent.Executors

// TODO: this is in https://github.com/pantsbuild/pants/pull/7506 -- merge that!!
case class BareBonesLogger(thisLevel: Level.Value) extends bloop.logging.Logger {
  import scala.Console.{ CYAN, GREEN, RED, YELLOW, RESET }

  val out = System.err

  def printError(message: => String): Unit = {
    val colored = s"$RED[error] $message$RESET"
    out.println(colored)
  }

  override def printDebug(message: String): Unit = log(Level.Debug, message)

  override def asDiscrete: Logger = BareBonesLogger(Level.Info)

  override def asVerbose: Logger = BareBonesLogger(Level.Debug)

  override def debug(message: String)(implicit _ctx: DebugFilter): Unit = log(Level.Debug, message)

  override def debugFilter: DebugFilter = DebugFilter.All

  override def isVerbose: Boolean = thisLevel >= Level.Debug

  override def name: String = "pants-bloop-logger"

  override def ansiCodesSupported(): Boolean = true

  override def error(message: String): Unit = log(Level.Error, message)

  override def info(message: String): Unit = log(Level.Info, message)

  override def warn(message: String): Unit = log(Level.Warn, message)

  override def trace(t: Throwable): Unit = out.println(StackTrace.trimmed(t, 0))

  // FIXME: make use of the origin id!
  override def withOriginId(originId: Option[String]): bloop.logging.Logger = this

  def log(
    level: Level.Value,
    message: => String
  ): Unit = {
    if (level >= thisLevel) {
      val (colorStart, prefix) = level match {
        case Level.Debug => (CYAN, "[debug]")
        case Level.Info => (GREEN, "[info]")
        case Level.Warn => (YELLOW, "[warn]")
        case Level.Error => (RED, "[error]")
      }
      val colored = s"$colorStart$prefix $message$RESET"
      out.println(colored)
    }
  }
}

object PantsCompileMain {
  val bloopVersion = BuildInfo.version
  val bspVersion = BuildInfo.bspVersion

  // implicit lazy val scheduler: Scheduler = Scheduler.Implicits.global
  implicit lazy val scheduler: Scheduler = Scheduler(
    Executors.newFixedThreadPool(10),
    ExecutionModel.AlwaysAsyncExecution
  )
  lazy val ioScheduler: Scheduler = Scheduler(
    Executors.newFixedThreadPool(12),
    ExecutionModel.AlwaysAsyncExecution
  )

  def bufferInput(is: java.io.InputStream): java.io.BufferedReader = new java.io.BufferedReader(
    new java.io.InputStreamReader(is))
  def bufferOutput(os: java.io.OutputStream): java.io.PrintWriter = new java.io.PrintWriter(os)

  def err[S](r: Either[_, S]): S = r match {
    case Left(s) => throw new Exception(s"error: $s")
    case Right(result) => result
  }

  def exitOnError[T](t: Task[T])(implicit logger: Logger): Task[T] = t.onErrorHandle {
    case e => {
      logger.trace(e)
      System.err.println(s"omg!!! $e")
      sys.exit(1)
    }
  }

  def parseJsonLines(is: java.io.BufferedReader): Observable[Json] = Observable.suspend(
    Observable.fromIterable(
      Stream.continually(is.readLine)
        .takeWhile(_ != null)
        .map(parse(_)).map(err(_))))

  def main(args: Array[String]): Unit = {
    val (Array(logLevelArg, targetMappingFileArg), compileTargets) = {
      val index = args.indexOf("--")
      if (index == -1) (args, Array.empty[String])
      else args.splitAt(index)
    }
    val logLevel = logLevelArg match {
      case "debug" => Level.Debug
      case "info" => Level.Info
      case "warn" => Level.Warn
      case "error" => Level.Error
      case x => throw new Exception(s"unrecognized log level argument '$x'")
    }
    val targetMappingFile = Path(targetMappingFileArg)
    val targetMappingSource = Source.fromFile(targetMappingFile.toNIO.toFile)
      .getLines
      .mkString("\n")
    val targetMappingJson: Json = err(parse(targetMappingSource))
    val targetMapping = err(targetMappingJson.as[Map[String, (String, Seq[String])]])

    val launcherIn = new PipedInputStream()
    val clientOut = new PipedOutputStream(launcherIn)

    val clientIn = new PipedInputStream()
    val launcherOut = new PipedOutputStream(clientIn)

    val startedServer = Promise[Unit]()

    implicit val logger: Logger = new BareBonesLogger(logLevel)

    val task = Task.fromFuture(startedServer.future).flatMap { Unit =>
      val bspLogger = new BspClientLogger(logger)

      implicit val bspClient = new BloopLanguageClient(clientOut, bspLogger)
      val messages = BaseProtocolMessage.fromInputStream(clientIn, bspLogger)

      implicit val _ctx: DebugFilter = DebugFilter.All

      val services = Services
        .empty(bspLogger)
        .notification(endpoints.Build.showMessage) {
          case bsp.ShowMessageParams(bsp.MessageType.Log, _, _, msg) => logger.debug(msg)
          case bsp.ShowMessageParams(bsp.MessageType.Info, _, _, msg) => logger.info(msg)
          case bsp.ShowMessageParams(bsp.MessageType.Warning, _, _, msg) => logger.warn(msg)
          case bsp.ShowMessageParams(bsp.MessageType.Error, _, _, msg) => logger.error(msg)
        }.notification(endpoints.Build.logMessage) {
          case bsp.LogMessageParams(bsp.MessageType.Log, _, _, msg) => logger.debug(msg)
          case bsp.LogMessageParams(bsp.MessageType.Info, _, _, msg) => logger.info(msg)
          case bsp.LogMessageParams(bsp.MessageType.Warning, _, _, msg) => logger.warn(msg)
          case bsp.LogMessageParams(bsp.MessageType.Error, _, _, msg) => logger.error(msg)
        }.notification(endpoints.Build.publishDiagnostics) {
          case bsp.PublishDiagnosticsParams(uri, _, _, diagnostics, _) =>
            // We prepend diagnostics so that tests can check they came from this notification
            def printDiagnostic(d: bsp.Diagnostic): String = s"[diagnostic] ${d.message} ${d.range}"
            diagnostics.foreach { d =>
              d.severity match {
                case Some(bsp.DiagnosticSeverity.Error) => logger.error(printDiagnostic(d))
                case Some(bsp.DiagnosticSeverity.Warning) => logger.warn(printDiagnostic(d))
                case Some(bsp.DiagnosticSeverity.Information) => logger.info(printDiagnostic(d))
                case Some(bsp.DiagnosticSeverity.Hint) => logger.debug(printDiagnostic(d))
                case None => logger.debug(printDiagnostic(d))
              }
            }
        }.notification(endpoints.Build.taskStart) {
          case bsp.TaskStartParams(_, _, Some(message), _, _) =>
            logger.info(s"Task started: $message")
          case _ => ()
        }.notification(endpoints.Build.taskProgress) {
          case bsp.TaskProgressParams(_, _, Some(message), Some(total), Some(progress), Some(unit), _, _) =>
            // logger.debug(s"Task progress ($progress/$total $unit): $message")
            ()
          case bsp.TaskProgressParams(_, _, Some(message), _, _, _, _, _) =>
            // logger.debug(s"Task progress: $message")
            ()
          case _ => ()
        }.notification(endpoints.Build.taskFinish) {
          case bsp.TaskFinishParams(_, _, Some(message), status, _, _) => status match {
            case bsp.StatusCode.Ok => logger.info(s"Task finished with status [$status]: $message")
            case bsp.StatusCode.Error => logger.error(s"Task finished with status [$status]: $message")
            case bsp.StatusCode.Cancelled => logger.warn(s"Task finished with status [$status]: $message")
          }
          // NB: Currently not relevant -- this is how we can hack remote compiles via pants if we
          // wanted to.
          case bsp.TaskFinishParams(_, _, _, _, Some("bloop-hacked-remote-compile-request"), Some(data)) =>
            val msg = PantsCompileRequest(data.asObject.get.apply("sources").get.as[Seq[String]].right.get)
            System.out.println(msg.intoMessage.asSprayJson)
          case _ => ()
        }

      val bspServer = new BloopLanguageServer(messages, bspClient, services, scheduler, bspLogger)
      val runningClientServer = exitOnError(bspServer.startTask).runAsync(scheduler)

      def ack(a: Ack): Unit = a match {
        case Ack.Continue => ()
        case Ack.Stop => throw new Exception("stopped???")
      }

      val bspCompileInteraction = endpoints.Build.initialize.request(bsp.InitializeBuildParams(
        displayName = "pants-bloop-client",
        version = bloopVersion,
        bspVersion = bspVersion,
        rootUri = bsp.Uri(Environment.cwd.toUri),
        capabilities = bsp.BuildClientCapabilities(List("scala", "java")),
        data = Some(targetMapping.asJson),
      )).map(err(_))
        .flatMap { result =>
          val resultData = result.data.get.as[Map[String, Boolean]].right.get
          assert(resultData("received_target_mapping"))
          logger.debug(s"initializeResult: $result")
          Task.fromFuture(endpoints.Build.initialized.notify(bsp.InitializedBuildParams()))
        }.map(ack(_))
        .flatMap { Unit =>
          endpoints.Workspace.buildTargets.request(bsp.WorkspaceBuildTargetsRequest())
        }.map(err(_))
        .map(_.targets)
        .flatMap { targets =>
          val targetIds = compileTargets.toSet
          val matchingTargets = targets.filter(_.displayName.filter(targetIds).isDefined).toList
          val mIds = matchingTargets.flatMap(_.displayName)
          logger.debug(s"matchingTargets: $mIds")

          endpoints.BuildTarget.compile.request(bsp.CompileParams(
            targets = matchingTargets.map(_.id).toList,
            originId = None,
            arguments = None
          ))
        }.map(err(_))
        .map {
          case bsp.CompileResult(_, bsp.StatusCode.Ok,
            Some("project-name-classes-dir-mapping"),
            Some(mapping)) => {
            logger.debug(s"mapped: $mapping")

            val outputDir = pwd / ".pants.d" / ".tmp"
            rm(outputDir)
            mkdir(outputDir)
            val nonTempDirMapping: Map[String, Path] = err(mapping.as[Map[String, String]]).map {
              case (targetId, tempClassesDir) =>
                val curTargetOutputDir = outputDir / RelPath(targetId)
                logger.debug(s"copying temp dir $tempClassesDir to $curTargetOutputDir!!")
                // TODO: for some reason ammonite-ops `cp` just hangs here???
                %%("cp", "-r", Path(tempClassesDir).toString, curTargetOutputDir.toString)(pwd)
                (targetId -> curTargetOutputDir)
            }.toMap

            val msg = BloopCompileSuccess(nonTempDirMapping)
            System.out.println(msg.intoMessage.asSprayJson)
            System.out.close()
            sys.exit(0)
            ()
          }
          case x => throw new Exception(s"compile failed: $x")
        }
        .map { Unit =>
          System.out.close()
          sys.exit(0)
        }

      Task.fork(exitOnError(bspCompileInteraction))
    }.runAsync(scheduler)

    val launcherTask = Task(new LauncherMain(
      clientIn = launcherIn,
      clientOut = launcherOut,
      out = System.err,
      charset = StandardCharsets.UTF_8,
      shell = Shell.default,
      nailgunPort = None,
      startedServer = startedServer,
      generateBloopInstallerURL = Installer.defaultWebsiteURL(_)
    ).main(Array(bloopVersion)))

    exitOnError(launcherTask).runAsync(scheduler)
  }
}
