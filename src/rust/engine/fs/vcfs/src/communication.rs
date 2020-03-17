use super::pants_vcfs_interface::{self, TVcfsServerSyncClient};

use parking_lot::Mutex;
use thrift::protocol::{TBinaryInputProtocol, TBinaryOutputProtocol};

use std::io;
use std::net::Shutdown;
use std::ops::{Deref, DerefMut};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::Arc;

#[derive(Debug)]
pub enum CommunicationError {
  S(String),
}

pub struct Socket {
  pub path: PathBuf,
  pub stream: UnixStream,
}

impl Socket {
  pub fn create<P: AsRef<Path>>(path: &P) -> io::Result<Self> {
    let stream = UnixStream::connect(path)?;
    Ok(Socket {
      path: path.as_ref().to_path_buf(),
      stream,
    })
  }
}

impl Drop for Socket {
  fn drop(&mut self) {
    self.stream.shutdown(Shutdown::Both).unwrap();
  }
}

#[derive(Clone)]
pub struct SocketWrapper {
  inner: Arc<Mutex<Socket>>,
}

impl SocketWrapper {
  pub fn new(inner: Socket) -> Self {
    SocketWrapper {
      inner: Arc::new(Mutex::new(inner)),
    }
  }
}

impl io::Read for SocketWrapper {
  fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
    self.inner.lock().stream.read(buf)
  }
}

impl io::Write for SocketWrapper {
  fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
    self.inner.lock().stream.write(buf)
  }

  fn flush(&mut self) -> io::Result<()> {
    self.inner.lock().stream.flush()
  }
}

type BinarySocketIn = TBinaryInputProtocol<SocketWrapper>;
type BinarySocketOut = TBinaryOutputProtocol<SocketWrapper>;

struct ThriftSocket {
  pub input: BinarySocketIn,
  pub output: BinarySocketOut,
}

impl ThriftSocket {
  pub fn from_socket(socket: Socket) -> Self {
    let wrapper = SocketWrapper::new(socket);
    let input = TBinaryInputProtocol::new(wrapper.clone(), true);
    let output = TBinaryOutputProtocol::new(wrapper.clone(), true);
    ThriftSocket { input, output }
  }
}

type BinarySyncServer = pants_vcfs_interface::VcfsServerSyncClient<BinarySocketIn, BinarySocketOut>;

pub struct VcfsClient {
  client: BinarySyncServer,
}

impl Deref for VcfsClient {
  type Target = BinarySyncServer;

  fn deref(&self) -> &BinarySyncServer {
    &self.client
  }
}

impl DerefMut for VcfsClient {
  fn deref_mut(&mut self) -> &mut BinarySyncServer {
    &mut self.client
  }
}

impl VcfsClient {
  fn from_socket(socket: Socket) -> Self {
    let ThriftSocket { input, output } = ThriftSocket::from_socket(socket);
    let client = pants_vcfs_interface::VcfsServerSyncClient::new(input, output);
    VcfsClient { client }
  }

  pub fn from_socket_path<P: AsRef<Path>>(p: &P) -> io::Result<Self> {
    let socket = Socket::create(p)?;
    Ok(Self::from_socket(socket))
  }

  pub fn do_expand_globs_call(
    &mut self,
    expand_globs_message: pants_vcfs_interface::ExpandGlobsMessage,
  ) -> Result<Vec<pants_vcfs_interface::FileWithContentsDescriptor>, CommunicationError> {
    eprintln!("message was: {:?}", &expand_globs_message);
    match self.expand_globs(expand_globs_message.clone()) {
      Err(e) => Err(CommunicationError::S(format!(
        "error expanding globs from message {:?}: {:?}",
        expand_globs_message, e
      ))),
      Ok(pants_vcfs_interface::GlobExpansionComplete {
        message_id:
          Some(pants_vcfs_interface::MessageId {
            id: Some(message_id),
            ..
          }),
        status: Some(status),
        all_files,
        error_text,
        ..
      }) => match status {
        pants_vcfs_interface::GlobExpansionResultCode::Error => {
          Err(CommunicationError::S(format!(
            "glob expansion RPC call for message {:?} failed with error {:?}!",
            expand_globs_message, error_text,
          )))
        }
        pants_vcfs_interface::GlobExpansionResultCode::Ok => {
          assert_eq!(
            message_id,
            expand_globs_message.message_id.unwrap().id.unwrap()
          );
          eprintln!("all_files was: {:?}", all_files);
          let all_files = all_files.unwrap_or_else(Vec::new);
          Ok(all_files)
        }
      },
      Ok(x) => unimplemented!(
        "unrecognized glob expansion for message {:?}: {:?}",
        expand_globs_message,
        x
      ),
    }
  }
}
