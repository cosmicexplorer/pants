# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use our custom Centos6 image for binary compatibility with old linux distros.
FROM pantsbuild/centos6:latest

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

# Populate the bashrc with pyenv initialization commands. The PATH was set in the centos6 image when
# installing pythons with pyenv. This needs to be done before the VOLUME command, as all changes to
# that directory are discarded afterwards.
RUN mkdir -p /travis/home
RUN echo >> /travis/home/.bashrc 'eval "$(pyenv init -)"'
RUN echo >> /travis/home/.bashrc 'eval "$(pyenv virtualenv-init -)"'

# Setup a non-root user to execute the build under (avoids problems with npm install).
ARG TRAVIS_USER=travis_ci
ARG TRAVIS_UID=1000
ARG TRAVIS_GROUP=root
ARG TRAVIS_GID=0

RUN groupadd --gid ${TRAVIS_GID} ${TRAVIS_GROUP} || true
RUN useradd -d /travis/home -g ${TRAVIS_GROUP} --uid ${TRAVIS_UID} ${TRAVIS_USER}

RUN mkdir -p /travis/workdir
RUN chown -R ${TRAVIS_USER}:${TRAVIS_GROUP} /travis/home
RUN chmod u+rwx /travis/home
RUN chown -R ${TRAVIS_USER}:${TRAVIS_GROUP} /travis/workdir
RUN chmod u+rwx /travis/workdir

USER ${TRAVIS_USER}:${TRAVIS_GROUP}

# Our newly created user is unlikely to have a sane environment: set a locale at least.
ENV LC_ALL="en_US.UTF-8"

# Setup mount points for the travis ci user & workdir.
VOLUME /travis/home
VOLUME /travis/workdir

WORKDIR /travis/workdir
