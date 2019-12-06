import json
import os
import sys

from pex import resolver
from pex.common import open_zip
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.util import CacheHelper
from pex.variables import ENV

self = sys.argv[0]
ipex_file = '{}.ipex'.format(os.path.splitext(self)[0])

if not os.path.isfile(ipex_file):
  print('Hydrating {} to {}'.format(self, ipex_file))

  ptex_pex_info = PexInfo.from_pex(self)
  code_root = os.path.join(ptex_pex_info.zip_unsafe_cache, ptex_pex_info.code_hash)
  with open_zip(self) as zf:
    # Populate the pex with the pinned requirements and distribution names & hashes.
    ipex_info = PexInfo.from_json(zf.read('IPEX-INFO'))
    ipex_builder = PEXBuilder(pex_info=ipex_info)

    # Populate the pex with the needed code.
    ptex_info = json.loads(zf.read('PTEX-INFO').decode('utf-8'))
    for path in ptex_info['code']:
      ipex_builder.add_source(os.path.join(code_root, path), path)

  # Perform a fully pinned intransitive resolve to hydrate the install cache (not the
  # pex!).
  resolver_settings = ptex_info['resolver_settings']
  resolved_distributions = resolver.resolve(
    requirements=[str(req) for req in ipex_info.requirements],
    cache=ipex_info.pex_root,
    transitive=False,
    **resolver_settings
  )

  ipex_builder.build(ipex_file)

os.execv(ipex_file, [ipex_file] + sys.argv[1:])
