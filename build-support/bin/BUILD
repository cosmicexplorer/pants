# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
  name = 'bash_scripts',
  sources = ['*.sh'],
)

python_tests(
  name="tests",
  # reversion_test.py times out occasionally.
  timeout=90,
)

pex_binary(
   name = 'bootstrap_and_deploy_ci_pants_pex',
   sources = ['bootstrap_and_deploy_ci_pants_pex.py'],
)

pex_binary(
  name = 'check_banned_imports',
  sources = ['check_banned_imports.py'],
)

pex_binary(
  name = 'check_inits',
  sources = ['check_inits.py'],
)

pex_binary(
  name = 'ci',
  sources = ['ci.py'],
)

python_library(
  name = 'common',
  sources = ['common.py'],
)

pex_binary(
  name = 'deploy_to_s3',
  sources = ['deploy_to_s3.py'],
)

pex_binary(
  name = 'generate_travis_yml',
  sources = ['generate_travis_yml.py'],
)

pex_binary(
  name = 'generate_docs',
  sources = ['generate_docs.py'],
  dependencies = [
    ':docs_templates'
  ],
)

resources(
  name = 'docs_templates',
  sources = ['docs_templates/*.mustache'],
)

pex_binary(
  name = 'get_rbe_token',
  sources = ['get_rbe_token.py'],
)

pex_binary(
  name='reversion',
  sources=["reversion.py"],
)

pex_binary(
  name = 'shellcheck',
  sources = ['shellcheck.py'],
)

# TODO: rename this to `release.py` once done porting Bash to Python.
pex_binary(
  name = "packages",
  sources = ["packages.py"],
)

python_tests()