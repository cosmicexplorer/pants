# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class SbtDist(Target):

  @classmethod
  def alias(cls):
    return 'sbt_dist'

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               project_name=None,
               **kwargs):

    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources, address.spec_path, key_arg='sources'),
    })
    super(SbtDist, self).__init__(address=address, payload=payload, **kwargs)

    self._project_name = project_name
