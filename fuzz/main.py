from __future__ import absolute_import, division, print_function, unicode_literals

import sys
import time

import afl
from fuzz import untar_stream_into_tmp_dir

from pants.base.exiter import Exiter
from pants.bin.pants_runner import PantsRunner


def main():
  afl.init()

  with untar_stream_into_tmp_dir(sys.stdin):
    start_time = time.time()

    exiter = Exiter()
    exiter.set_except_hook()

    # pants_run_env = os.environ.copy()
    pants_run_env = {}
    pants_run_env['PANTS_ENABLE_PANTSD'] = 'False'

    # pants_smoke_test_cmd = ['./pants', 'run', '//:bin']
    # TODO: currently this just lists everything in the current pants repo, not the one we just
    # untarred into a temp dir!
    pants_smoke_test_cmd = ['./pants', 'list', '::']

    try:
      PantsRunner(exiter,
                  args=pants_smoke_test_cmd,
                  env=pants_run_env,
                  start_time=start_time).run()
    except KeyboardInterrupt:
      exiter.exit_and_fail('Interrupted by user.')
