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
from pkg_resources import Distribution, EggInfoDistribution

from pex import resolver
from pex.common import open_zip
from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

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


def _make_acceptable_distribution_from_downloaded_file(downloaded_file, name, version, output_dir):
    _, ext = os.path.splitext(downloaded_file)
    if ext in ['.whl', '.WHL']:
        # Wheels can be easily consumed via PEXBuilder.add_distribution()!!
        return Distribution(
            location=downloaded_file,
            project_name=name,
            version=version,
        )

    # Otherwise, we'll have to build the .tar.gz projects ourselves. Let's make this fast.
    assert ext == '.gz', 'extension {} was not recognized for downloaded file {}'.format(ext, downloaded_file)
    shutil.unpack_archive(downloaded_file, output_dir)
    expected_newly_created_subdir = os.path.join(output_dir, '{}-{}'.format(name, version))
    assert os.path.isdir(expected_newly_created_subdir), 'expected {} to be an existing directory: output dir had: {}'.format(expected_newly_created_subdir, os.listdir(output_dir))

    major, minor, *_ = sys.version_info
    interpreter_subdir_name = 'python{}.{}'.format(major, minor)

    possibly_canonical_site_packages_subdir = os.path.join(
        output_dir, 'lib', interpreter_subdir_name, 'site-packages')

    subprocess.check_call(
        [sys.executable, 'setup.py', 'install', '--prefix', output_dir],
        env={
            'PYTHONPATH': possibly_canonical_site_packages_subdir,
            'PATH': os.environ['PATH'],
        },
        cwd=expected_newly_created_subdir,
    )

    assert os.path.isdir(possibly_canonical_site_packages_subdir), 'expected {} to exist!!'.format(possibly_canonical_site_packages_subdir)

    expected_site_packages_glob = re.sub(r'[-_\+]', '*', '{}*{}*.egg*'.format(name, version))
    egg_info_files = glob.glob(os.path.join(possibly_canonical_site_packages_subdir, expected_site_packages_glob))
    assert len(egg_info_files) == 1, 'expected egg info for glob {} to exist! dir contained: {}'.format(expected_site_packages_glob, os.listdir(possibly_canonical_site_packages_subdir))

    egg_dist = EggInfoDistribution.from_filename(egg_info_files[0])
    # NB: We have to make sure the location is set to a directory, otherwise the pex builder will
    # reject it outright. The containing directory should work just fine, after we've gotten all the
    # *correct* info by *first* scanning the *actual* egg-info file!
    egg_dist.location = os.path.dirname(egg_dist.location)

    return egg_dist


def _resolve_requirements_from_urls(output_dir, pex_builder, requirements_with_urls):
    pool = ThreadPool(processes=len(requirements_with_urls))

    urls_with_download_filenames = []
    for req_with_url in requirements_with_urls:
        name = req_with_url['name']
        version = req_with_url['version']
        url = req_with_url['url']
        download_filename = _extract_download_filename(name, url)
        urls_with_download_filenames.append((name, version, url, download_filename))

    def download_dist_from_url(url_to_download):
        name, version, url, download_filename = url_to_download
        download_path = os.path.join(output_dir, download_filename)
        _log('downloading {} into {}'.format(url, download_path))

        try:
            with urlopen(url) as response,\
                 open(download_path, 'wb') as download_file_stream:

                shutil.copyfileobj(response, download_file_stream)
        except Exception as e:
            _log('error when downloading {} into {}: {}'
                 .format(url, download_filename, e))
            raise

        dist = _make_acceptable_distribution_from_downloaded_file(
            download_path, name=name, version=version, output_dir=output_dir)

        pex_builder.add_distribution(dist, dist_name=name)

        return (name, version)

    try:
        yield from pool.imap_unordered(download_dist_from_url, urls_with_download_filenames)
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

    for name, version in _resolve_requirements_from_urls(
            output_dir=os.path.join(os.getcwd(), 'tmp-3'),
            # output_dir=td,
            pex_builder=bootstrap_builder,
            requirements_with_urls=requirements_with_urls):
        _log('hydrated {} at {}'.format(name, version))

    bootstrap_builder.build(hydrated_pex_file, bytecode_compile=False)


def main(self):
    filename_base, ext = os.path.splitext(self)

    # If the ipex (this pex) is already named '.pex', ensure the output filename doesn't collide by
    # inserting an intermediate '.ipex'!
    if ext == ".pex":
        hydrated_pex_file = "{filename_base}.ipex.pex".format(filename_base=filename_base)
    else:
        hydrated_pex_file = "{filename_base}.pex".format(filename_base=filename_base)

    if not os.path.exists(hydrated_pex_file):
        _log("Hydrating {} to {}...".format(self, hydrated_pex_file))
        _hydrate_pex_file(self, hydrated_pex_file)

    os.execv(sys.executable, [sys.executable, hydrated_pex_file] + sys.argv[1:])


if __name__ == "__main__":
    self = sys.argv[0]
    main(self)
