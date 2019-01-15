# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use centos6 for compatibility with glibc 2.12.
FROM centos:6

# Install a (more) modern gcc, and a JDK.
# Also install sqlite-devel because python 3 errors on startup if not -- see
# https://stackoverflow.com/a/39907500/2518889.
RUN yum -y update
# TODO: figure out why this needs to be installed first for /usr/bin/scl to work!
RUN yum install -y centos-release-scl
RUN yum install -y devtoolset-7-gcc{,-c++} \
  git \
  java-1.8.0-openjdk-devel \
  libffi{,-devel} \
  openssl-devel \
  sqlite-devel

# Install the desired versions of python 2 and 3.
ARG PYTHON_2_VERSION=2.7.13
ARG PYTHON_3_VERSION=3.6.8
# NB: PYENV_ROOT must be set in the environment for `pyenv install` to work, otherwise it will
# mysteriously fail to find the `install` command.
ENV PYENV_ROOT /pyenv-docker-build
RUN curl -L -v https://pyenv.run | bash
# https://github.com/pyenv/pyenv-installer tells you to *remove* this from your .bashrc on
# uninstall, but it doesn't appear to *add* it there on install, which is confusing.
RUN echo >> ~/.bashrc 'eval "$(pyenv init -)"'
RUN echo >> ~/.bashrc 'eval "$(pyenv virtualenv-init -)"'
ENV PATH "${PYENV_ROOT}/bin:${PATH}"
RUN pyenv update
# `scl enable devtoolset-7` puts the gcc we just installed on the PATH for that command.
RUN scl enable devtoolset-7 -- pyenv install ${PYTHON_2_VERSION}
RUN scl enable devtoolset-7 -- pyenv install ${PYTHON_3_VERSION}
RUN pyenv global ${PYTHON_2_VERSION} ${PYTHON_3_VERSION}

# By default, execute in an environment with python27 enabled.
ENTRYPOINT ["/usr/bin/scl", "enable", "devtoolset-7",  "--"]
