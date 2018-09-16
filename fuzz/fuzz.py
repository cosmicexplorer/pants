import tarfile
from contextlib import contextmanager

from pants.util.contextutil import pushd, temporary_dir


@contextmanager
def tar_from_stream(stream):
  tarfile.open(mode='r|', fileobj=stream)


def is_evil_path(file_path):
  if os.path.isabs(file_path):
    return True

  for component in file_path.split(os.sep):
    if component == '..':
      return True

  return False


def get_relevant_tar_members(tar_file):
  members = tar_file.getmembers()
  for m in members:
    if m.isfile() or m.isdir():
      if is_evil_path(m.name):
        continue
      yield m
    if m.issym():
      # TODO: is_evil_path() is insufficient here -- symlinks can have relative locations outside
      # their containing directory (therefore containing .. in the target path).
      if is_evil_path(m.name) or is_evil_path(m.linkname):
        continue
      yield m


@contextmanager
def extract_tar_into_tmp_dir(tar_file):
  with temporary_dir() as tmpdir:
    relevant_members = get_relevant_tar_members(tar_file)
    tar_file.extractall(path=tmpdir, members=relevant_members)
    yield tmpdir


@contextmanager
def untar_stream_into_tmp_dir(stream):
  with tar_from_stream(stream) as tar_file:
    with extract_tar_into_tmp_dir(tar_file) as tmpdir:
      with pushd(tmpdir):
        yield
