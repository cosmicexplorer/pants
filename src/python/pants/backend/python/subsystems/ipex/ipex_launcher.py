# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Entrypoint script for a "dehydrated" .ipex file generated with --generate-ipex.

This script will "hydrate" a normal .pex file in the same directory, then execute it.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from multiprocessing.pool import ThreadPool
from urllib.request import urlopen
from pkg_resources import Distribution

from pex import resolver
from pex.common import open_zip
from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.resolver import resolve

APP_CODE_PREFIX = "user_files/"


def _strip_app_code_prefix(path):
    if not path.startswith(APP_CODE_PREFIX):
        raise ValueError(
            "Path {path} in IPEX-INFO did not begin with '{APP_CODE_PREFIX}'.".format(
                path=path, APP_CODE_PREFIX=APP_CODE_PREFIX
            )
        )
    return path[len(APP_CODE_PREFIX) :]


def _log(message):
    sys.stderr.write(message + "\n")


def modify_pex_info(pex_info, **kwargs):
    new_info = json.loads(pex_info.dump())
    new_info.update(kwargs)
    return PexInfo.from_json(json.dumps(new_info))


def _extract_download_filename(name, url):
    matched = re.match(r'^https?://.*/([^/]+)\.(whl|WHL|tar\.gz)#sha256=.*$', url)
    if not matched:
        raise TypeError('url for project {} did not match expected format: {}'.format(name, url))
    filename_base, ext = matched.groups()
    download_filename = '{}.{}'.format(filename_base, ext)
    return download_filename


def _download_urls_parallel(output_dir, requirements_with_urls):
    pool = ThreadPool(processes=len(requirements_with_urls))

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    def download_dist_from_url(url_to_download):
        name, version, url, download_filename = url_to_download
        download_path = os.path.join(output_dir, download_filename)

        if not os.path.isfile(download_path):
            _log('downloading {} into {}'.format(url, download_path))

            try:
                with urlopen(url) as response,\
                     open(download_path, 'wb') as download_file_stream:

                    shutil.copyfileobj(response, download_file_stream)
            except Exception as e:
                _log('error when downloading {} into {}: {}'
                     .format(url, download_filename, e))
                raise

        return (name, version, download_path)

    try:
        yield from pool.imap_unordered(download_dist_from_url, requirements_with_urls)
    finally:
        pool.close()


def _hydrate_pex_file(self, hydrated_pex_file):
    # We extract source files into a temporary directory before creating the pex.
    td = tempfile.mkdtemp()

    with open_zip(self) as zf:
        # Populate the pex with the pinned requirements and distribution names & hashes.
        bootstrap_info = PexInfo.from_json(zf.read("BOOTSTRAP-PEX-INFO"))
        bootstrap_builder = PEXBuilder(pex_info=bootstrap_info, interpreter=PythonInterpreter.get())

        # Populate the pex with the needed code.
        try:
            ipex_info = json.loads(zf.read("IPEX-INFO").decode("utf-8"))
            for path in ipex_info["code"]:
                unzipped_source = zf.extract(path, td)
                bootstrap_builder.add_source(
                    unzipped_source, env_filename=_strip_app_code_prefix(path)
                )
        except Exception as e:
            raise ValueError(
                "Error: {e}. The IPEX-INFO for this .ipex file was:\n{info}".format(
                    e=e, info=json.dumps(ipex_info, indent=4)
                )
            )

    # Perform a fully pinned intransitive resolve, in parallel directly from requirement URLs.
    requirements_with_urls = ipex_info['requirements_with_urls']

    ipex_downloads_cache = os.path.join(
        os.path.dirname(self),
        '.ipex-downloads')

    wheels = []
    non_wheels = []
    for req_with_url in requirements_with_urls:
        name = req_with_url['name']
        version = req_with_url['version']
        url = req_with_url['url']
        download_filename = _extract_download_filename(name, url)
        payload = (name, version, url, download_filename)
        if download_filename.endswith('.whl'):
            wheels.append(payload)
        else:
            non_wheels.append(payload)

    non_wheel_output_dir = os.path.join(ipex_downloads_cache, 'non-wheel')
    # Block on all non-wheel requirements first because they're likely to be smaller, and we need to
    # do more work after downloading them too.
    all_non_wheel_requirements = [
        '{}=={}'.format(name, version)
        for name, version, _ in _download_urls_parallel(
                output_dir=non_wheel_output_dir,
                requirements_with_urls=non_wheels,
        )
    ]

    all_dists = []

    def add_dist(dist):
        bootstrap_builder.add_distribution(dist, dist_name=dist.project_name)
        bootstrap_builder.add_requirement(dist.as_requirement())

    dists = list(resolve(all_non_wheel_requirements,
                         interpreter=bootstrap_builder.interpreter,
                         build=True,
                         transitive=False,
                         find_links=[non_wheel_output_dir]))
    for resolved_dist in resolve(all_non_wheel_requirements,
                                 interpreter=bootstrap_builder.interpreter,
                                 build=True,
                                 transitive=False,
                                 find_links=[non_wheel_output_dir]):
        _log('wheelified non-wheel dist {}'.format(resolved_dist))
        add_dist(resolved_dist.distribution)

    for name, version, download_path in _download_urls_parallel(
            output_dir=os.path.join(ipex_downloads_cache, 'wheel'),
            requirements_with_urls=wheels):
        _log('hydrated {}=={} to {}'.format(name, version, download_path))
        add_dist(Distribution(
            location=download_path,
            project_name=name,
            version=version,
        ))

    bootstrap_builder.build(hydrated_pex_file, bytecode_compile=False)


def main(self):
    filename_base, ext = os.path.splitext(self)

    # If the ipex (this pex) is already named '.pex', ensure the output filename doesn't collide by
    # inserting an intermediate '.ipex'!
    if ext == ".pex":
        ext = '.ipex.pex'

    code_hash = PexInfo.from_pex(self).code_hash
    hydrated_pex_file = "{}-{}{}".format(filename_base, code_hash, ext)

    if not os.path.exists(hydrated_pex_file):
        _log("Hydrating {} to {}...".format(self, hydrated_pex_file))
        _hydrate_pex_file(self, hydrated_pex_file)

    os.execv(sys.executable, [sys.executable, hydrated_pex_file] + sys.argv[1:])


if __name__ == "__main__":
    self = sys.argv[0]
    main(self)
