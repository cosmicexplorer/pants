import sys
import time

import afl
from fuzz import *

from pants.base.build_environment import get_buildroot
from pants.bin.pants_runner import PantsRunner
from pants.util.contextutil import maybe_profiled, pushd


def main():
  afl.init()

  with untar_stream_into_tmp_dir(sys.stdin):
    start_time = time.time()

    exiter = Exiter()
    exiter.set_except_hook()

    pants_run_env = os.environ.copy()
    pants_run_env['PANTS_ENABLE_PANTSD'] = 'False'

    pants_smoke_test_cmd = ['./pants', 'options']

    with maybe_profiled(os.environ.get('PANTSC_PROFILE')):
      try:
        PantsRunner(exiter,
                    args=pants_smoke_test_cmd,
                    env=pants_run_env,
                    start_time=start_time).run()
      except KeyboardInterrupt:
        exiter.exit_and_fail('Interrupted by user.')
