# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Entrypoint script for a .ptex file generated with --generate-ptex.

This script will build a .ipex file into a temporary directory, then execute it. If
PANTS_PTEX_HYDRATE_ONLY_TO_IPEX=<filename> is set, however, the script will generate the ipex at
<filename>, then exit without executing the .ipex file.
"""

import json
import os
import sys
import tempfile

from pex import resolver
from pex.common import open_zip
from pex.fetcher import Fetcher, PyPIFetcher
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import matched_interpreters
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo


APP_CODE_PREFIX = 'user_files/'


def _strip_app_code_prefix(path):
  if not path.startswith(APP_CODE_PREFIX):
    raise ValueError(f"Path {path} in PTEX-INFO did not begin with '{APP_CODE_PREFIX}'.")
  return path[len(APP_CODE_PREFIX):]


HYDRATE_ONLY_NO_EXEC_ENV_VAR = 'PANTS_PTEX_HYDRATE_ONLY_TO_IPEX'


def main(self):
  filename_base, _ext = os.path.splitext(self)

  # Build a .ipex file in a new temporary dir, each time.
  td = tempfile.mkdtemp()
  hydrated_ipex_file = os.environ.get(HYDRATE_ONLY_NO_EXEC_ENV_VAR, None)
  whether_to_run = False
  if not hydrated_ipex_file:
    whether_to_run = True
    hydrated_ipex_file = os.path.join(td, '{}.ipex'.format(filename_base))

  sys.stderr.write('Hydrating {} to {}...\n'.format(self, hydrated_ipex_file))

  with open_zip(self) as zf:
    # Populate the pex with the pinned requirements and distribution names & hashes.
    ipex_info = PexInfo.from_json(zf.read('IPEX-INFO'))
    for interpreter in matched_interpreters(PythonInterpreter.all(),
                                            ipex_info.interpreter_constraints):
      ipex_builder = PEXBuilder(pex_info=ipex_info, interpreter=interpreter)
      break
    else:
      raise ValueError(f'Could not resolve interpreter for constraints {ipex_info.interpreter_constraints}. '
                       f'The IPEX-INFO for this .ptex was was:\n{ipex_info.dump(indent=4)}')

    # Populate the pex with the needed code.
    try:
      ptex_info = json.loads(zf.read('PTEX-INFO').decode('utf-8'))
      for path in ptex_info['code']:
        unzipped_source = zf.extract(path, td)
        ipex_builder.add_source(unzipped_source, env_filename=_strip_app_code_prefix(path))
    except Exception as e:
      raise ValueError(
        f"Error: {e}. The PTEX-INFO for this .ptex file was:\n{json.dumps(ptex_info, indent=4)}"
      ) from e

  # Perform a fully pinned intransitive resolve to hydrate the install cache.
  resolver_settings = ptex_info['resolver_settings']
  # TODO: Convert .indexes and .find_links into the old .fetchers until pants upgrades to pex 2.0!
  fetchers = [PyPIFetcher(url) for url in resolver_settings.pop('indexes')]
  fetchers.extend(Fetcher([url]) for url in resolver_settings.pop('find_links'))
  resolver_settings['fetchers'] = fetchers

  resolved_distributions = resolver.resolve(
    requirements=ipex_info.requirements,
    cache=ipex_info.pex_root,
    platform='current',
    transitive=False,
    interpreter=ipex_builder.interpreter,
    **resolver_settings
  )
  # TODO: this shouldn't be necessary, as we should be able to use the same 'distributions' from
  # IPEX-INFO. When the .ipex is executed, the normal pex bootstrap fails to see these requirements
  # or recognize that they should be pulled from the cache for some reason.
  for resolved_dist in resolved_distributions:
    ipex_builder.add_distribution(resolved_dist.distribution)

  ipex_builder.build(hydrated_ipex_file, bytecode_compile=False)

  if whether_to_run:
    os.execv(hydrated_ipex_file, [hydrated_ipex_file] + sys.argv[1:])


if __name__ == '__main__':
  self = sys.argv[0]
  main(self)
