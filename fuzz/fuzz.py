from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil
import tarfile
from builtins import str
from contextlib import contextmanager

from pants.util.contextutil import pushd, temporary_dir


def is_evil_path(file_path):
  if os.path.isabs(file_path):
    return True

  for component in file_path.split(os.sep):
    if component == b'..':
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
def extract_tar_into_tmp_dir(stream_tar_file):
  with temporary_dir() as tmpdir:
    tmp_tar_file_path = os.path.join(tmpdir, 'tmp.tar')
    # Copy the stream into a temporary file.
    with open(tmp_tar_file_path, 'wb') as tmp_tar_file_obj:
      shutil.copyfileobj(stream_tar_file, tmp_tar_file_obj)
    # Getting the members of a tar requires scanning the file to get the headers, which consumes the
    # file object: see https://stackoverflow.com/a/18624269/2518889.
    with tarfile.open(tmp_tar_file_path) as tar_for_members:
      relevant_members = list(get_relevant_tar_members(tar_for_members))
    # Read from the temporary file, and extract it.
    with tarfile.open(tmp_tar_file_path) as tar_for_extraction:
      tar_for_extraction.extractall(path=str(tmpdir).encode('utf-8'), members=relevant_members)
    # We don't need the tar file anymore.
    os.unlink(tmp_tar_file_path)
    yield tmpdir


@contextmanager
def untar_stream_into_tmp_dir(stream):
  with extract_tar_into_tmp_dir(stream) as tmpdir:
    with pushd(tmpdir):
      yield
