# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

HYDRATE_ONLY_NO_EXEC_ENV_VAR = 'PANTS_IPEX_HYDRATE_ONLY'

"""Entrypoint script for a .ipex file generated with --generate-ipex.

This script will build a normal fat pex file into a temporary directory, then execute it. If
{HYDRATE_ONLY_NO_EXEC_ENV_VAR}=<filename> is set, however, the script will generate the ipex at
<filename>, then exit without executing the .ipex file.
""".format(HYDRATE_ONLY_NO_EXEC_ENV_VAR=HYDRATE_ONLY_NO_EXEC_ENV_VAR)

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
    raise ValueError("Path {path} in IPEX-INFO did not begin with '{APP_CODE_PREFIX}'."
                     .format(path=path, APP_CODE_PREFIX=APP_CODE_PREFIX))
  return path[len(APP_CODE_PREFIX):]


def main(self):
  filename_base, _ext = os.path.splitext(self)

  # Build a .ipex file in a new temporary dir, each time.
  td = tempfile.mkdtemp()
  hydrated_pex_file = os.environ.get(HYDRATE_ONLY_NO_EXEC_ENV_VAR, None)
  whether_to_run = False
  if not hydrated_pex_file:
    whether_to_run = True
    hydrated_pex_file = os.path.join(td, '{}.pex'.format(filename_base))

  sys.stderr.write('Hydrating {} to {}...\n'.format(self, hydrated_pex_file))

  with open_zip(self) as zf:
    # Populate the pex with the pinned requirements and distribution names & hashes.
    bootstrap_info = PexInfo.from_json(zf.read('BOOTSTRAP-PEX-INFO'))
    for interpreter in matched_interpreters(PythonInterpreter.all(),
                                            bootstrap_info.interpreter_constraints):
      bootstrap_builder = PEXBuilder(pex_info=bootstrap_info, interpreter=interpreter)
      break
    else:
      raise ValueError('Could not resolve interpreter for constraints {constraints}. '
                       'The BOOTSTRAP-PEX-INFO for this .ipex was was:\n{info}'
                       .format(constraints=bootstrap_info.interpreter_constraints,
                               info=bootstrap_info.dump(indent=4)))

    # Populate the pex with the needed code.
    try:
      ipex_info = json.loads(zf.read('IPEX-INFO').decode('utf-8'))
      for path in ipex_info['code']:
        unzipped_source = zf.extract(path, td)
        bootstrap_builder.add_source(unzipped_source, env_filename=_strip_app_code_prefix(path))
    except Exception as e:
      raise ValueError("Error: {e}. The IPEX-INFO for this .ipex file was:\n{info}"
                       .format(e=e, info=json.dumps(ipex_info, indent=4)))

  # Perform a fully pinned intransitive resolve to hydrate the install cache.
  resolver_settings = ipex_info['resolver_settings']
  # TODO: Here we convert .indexes and .find_links into the old .fetchers until pants upgrades to
  # pex 2.0. At that time, we can remove anything relating to fetchers from `resolver_settings`, and
  # avoid removing the 'indexes' and 'find_links' keys, which are correct for pex 2.0.
  fetchers = [PyPIFetcher(url) for url in resolver_settings.pop('indexes')]
  fetchers.extend(Fetcher([url]) for url in resolver_settings.pop('find_links'))
  resolver_settings['fetchers'] = fetchers

  resolved_distributions = resolver.resolve(
    requirements=bootstrap_info.requirements,
    cache=bootstrap_info.pex_root,
    platform='current',
    transitive=False,
    interpreter=bootstrap_builder.interpreter,
    **resolver_settings
  )
  # TODO: this shouldn't be necessary, as we should be able to use the same 'distributions' from
  # BOOTSTRAP-PEX-INFO. When the .ipex is executed, the normal pex bootstrap fails to see these
  # requirements or recognize that they should be pulled from the cache for some reason.
  for resolved_dist in resolved_distributions:
    bootstrap_builder.add_distribution(resolved_dist.distribution)

  bootstrap_builder.build(hydrated_pex_file, bytecode_compile=False)

  if whether_to_run:
    os.execv(hydrated_pex_file, [hydrated_pex_file] + sys.argv[1:])


if __name__ == '__main__':
  self = sys.argv[0]
  main(self)
