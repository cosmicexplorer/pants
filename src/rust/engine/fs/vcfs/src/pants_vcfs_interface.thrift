namespace rs pants_vcfs_interface
namespace cpp pants_vcfs_interface

struct MessageId {
  1: optional i64 id,
}

struct FileWithContentsDescriptor {
  1: optional string path;
  2: optional i64 contents_start,
  3: optional i64 contents_end,
}

enum GlobExpansionResultCode {
  OK = 1,
  ERROR = 2,
}

struct GlobExpansionComplete {
  1: optional MessageId message_id,
  2: optional GlobExpansionResultCode status,
  3: optional list<FileWithContentsDescriptor> all_files,
  4: optional string error_text,
}

enum StrictGlobMatching {
  ERROR = 1,
  WARN = 2,
  IGNORE = 3,
}

enum Conjunction {
  ALL_MATCH = 1,
  ANY_MATCH = 2,
}

struct PathGlobs {
  1: optional list<string> include_patterns,
  2: optional list<string> exclude_patterns,
  3: optional StrictGlobMatching strictness,
  4: optional Conjunction conjunction,
}

struct ExpandGlobsMessage {
  1: optional MessageId message_id,
  2: optional PathGlobs path_globs,
}

service VcfsServer {
  GlobExpansionComplete expandGlobs(1:ExpandGlobsMessage glob_expansion_request),
}
