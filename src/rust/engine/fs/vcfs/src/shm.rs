/* From https://gist.github.com/garcia556/8231e844a90457c99cc72e5add8388e4!! */

use super::mmap_bindings::{self, key_t, size_t, IPC_CREAT, IPC_R, IPC_W, SHM_RDONLY};
use super::pants_vcfs_interface;

use std::ffi::{self, CStr, CString};
use std::io;
use std::mem;
use std::ops::{Deref, DerefMut};
use std::os::{self, unix::ffi::OsStrExt};
use std::path::Path;
use std::ptr;
use std::slice;

#[derive(Debug)]
pub enum ShmError {
  S(String),
  NullTerminated(ffi::FromBytesWithNulError),
}

impl From<String> for ShmError {
  fn from(err: String) -> Self {
    ShmError::S(err)
  }
}

impl From<ffi::FromBytesWithNulError> for ShmError {
  fn from(err: ffi::FromBytesWithNulError) -> Self {
    ShmError::NullTerminated(err)
  }
}

#[derive(Copy, Clone)]
pub enum Permission {
  Read,
  Write,
}

pub struct ShmHandle {
  size_bytes: usize,
  shm_fd: os::raw::c_int,
  mmap_addr: *mut os::raw::c_void,
  permission: Permission,
}

impl Deref for ShmHandle {
  type Target = [u8];

  fn deref(&self) -> &[u8] {
    unsafe {
      slice::from_raw_parts(
        mem::transmute::<*mut os::raw::c_void, *const u8>(self.mmap_addr),
        self.size_bytes,
      )
    }
  }
}

impl DerefMut for ShmHandle {
  fn deref_mut(&mut self) -> &mut [u8] {
    unsafe {
      slice::from_raw_parts_mut(
        mem::transmute::<*mut os::raw::c_void, *mut u8>(self.mmap_addr),
        self.size_bytes,
      )
    }
  }
}

pub struct FileWithContents<'a> {
  pub path: &'a Path,
  pub contents: &'a [u8],
}

impl<'a> FileWithContents<'a> {
  pub fn from_shm_descriptor(
    bytes: &'a [u8],
    fd: &'a pants_vcfs_interface::FileWithContentsDescriptor,
  ) -> Self {
    match fd {
      pants_vcfs_interface::FileWithContentsDescriptor {
        path: Some(path),
        contents_start: Some(contents_start),
        contents_end: Some(contents_end),
        ..
      } => {
        assert!(contents_end >= contents_start);
        let path = Path::new(path);
        let contents = &bytes[(*contents_start as usize)..(*contents_end as usize)];
        FileWithContents { path, contents }
      }
      x => unimplemented!(
        "could not parse file with contents descriptor struct {:?}",
        x
      ),
    }
  }
}

impl ShmHandle {
  pub fn new(key: key_t, size_bytes: usize, permission: Permission) -> Result<Self, ShmError> {
    let fd_perm = match permission {
      Permission::Read => IPC_R,
      Permission::Write => IPC_R | IPC_W,
    };

    let shm_fd = unsafe {
      let fd = mmap_bindings::shmget(
        key,
        size_bytes as size_t,
        (IPC_CREAT | fd_perm) as os::raw::c_int,
      );
      if fd == -1 {
        let err = io::Error::last_os_error();
        return Err(ShmError::S(format!("failed to open SHM: {:?}", err)));
      }
      fd
    };

    let shmat_prot = match permission {
      Permission::Read => SHM_RDONLY,
      Permission::Write => 0,
    };
    let mmap_addr = unsafe {
      let addr = mmap_bindings::shmat(shm_fd, ptr::null(), shmat_prot as os::raw::c_int);
      #[allow(non_snake_case)]
      let MAP_FAILED = mem::transmute::<i64, *mut os::raw::c_void>(-1);
      if addr == MAP_FAILED {
        let err = io::Error::last_os_error();
        return Err(ShmError::S(format!(
          "failed to mmap SHM at fd {:?}: {:?}",
          shm_fd, err
        )));
      }
      addr
    };

    Ok(ShmHandle {
      size_bytes,
      shm_fd,
      mmap_addr,
      permission,
    })
  }
}

impl Drop for ShmHandle {
  fn drop(&mut self) {
    let rc = unsafe { mmap_bindings::shmdt(self.mmap_addr) };
    if rc == -1 {
      let err = io::Error::last_os_error();
      panic!("error dropping shm mapping: {:?}", err);
    }
  }
}
