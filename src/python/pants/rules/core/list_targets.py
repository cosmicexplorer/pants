# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from enum import Enum
from typing import Union

from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import FingerprintedTargetCollection, HydratedTargets
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get


class ListOptions(LineOriented, GoalSubsystem):
    """Lists all targets matching the target specs."""

    name = "list"

    class OutputFormat(Enum):
        address_specs = "address-specs"
        provides = "provides"
        documented = "documented"
        json = "json"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--provides",
            type=bool,
            removal_version="1.28.0.dev2",
            removal_hint="Use --output-format=provides instead!",
            help="List only targets that provide an artifact, displaying the columns specified by "
            "--provides-columns.",
        )
        register(
            "--provides-columns",
            default="address,artifact_id",
            help="Display these columns when --provides is specified. Available columns are: "
            "address, artifact_id, repo_name, repo_url, push_db_basedir",
        )

        register(
            "--documented",
            type=bool,
            removal_version="1.28.0.dev2",
            removal_hint="Use --output-format=documented instead!",
            help="Print only targets that are documented with a description.",
        )

        register(
            "--output-format",
            type=cls.OutputFormat,
            default=cls.OutputFormat.address_specs,
            help="How to format targets when printed to stdout.",
        )


def _make_provides_print_fn(provides_columns):
    extractors = dict(
        address=lambda target: target.address.spec,
        artifact_id=lambda target: str(target.adaptor.provides),
        repo_name=lambda target: target.adaptor.provides.repo.name,
        repo_url=lambda target: target.adaptor.provides.repo.url,
        push_db_basedir=lambda target: target.adaptor.provides.repo.push_db_basedir,
    )

    def print_provides(column_extractors, target):
        if getattr(target.adaptor, "provides", None):
            return " ".join(extractor(target) for extractor in column_extractors)

    try:
        column_extractors = [extractors[col] for col in (provides_columns.split(","))]
    except KeyError:
        raise Exception(
            "Invalid columns specified: {0}. Valid columns are: address, artifact_id, "
            "repo_name, repo_url, push_db_basedir.".format(provides_columns)
        )

    return lambda target: print_provides(column_extractors, target)


def _print_documented_target(target):
    description = getattr(target.adaptor, "description", None)
    if description:
        return "{0}\n  {1}".format(
            target.address.spec, "\n  ".join(description.strip().split("\n"))
        )


def _print_fingerprinted_target(fingerprinted_target):
    was_root = fingerprinted_target.was_root
    address = fingerprinted_target.address.spec
    target_type = fingerprinted_target.type_alias
    intransitive_fingerprint = fingerprinted_target.intransitive_fingerprint_arg
    transitive_fingerprint = fingerprinted_target.transitive_fingerprint_arg
    return json.dumps(
        {
            "was_root": was_root,
            "address": address,
            "target_type": target_type,
            "intransitive_fingerprint": intransitive_fingerprint,
            "transitive_fingerprint": transitive_fingerprint,
        }
    )


class List(Goal):
    subsystem_cls = ListOptions


@goal_rule
async def list_targets(console: Console, list_options: ListOptions, addresses: Addresses) -> List:
    provides = list_options.values.provides
    provides_columns = list_options.values.provides_columns
    documented = list_options.values.documented
    collection: Union[HydratedTargets, Addresses, FingerprintedTargetCollection]

    output_format = list_options.values.output_format

    # TODO: Remove when these options have completed their deprecation cycle!
    if provides:
        output_format = ListOptions.OutputFormat.provides
    elif documented:
        output_format = ListOptions.OutputFormat.documented

    # TODO: a match() method for Enums which allows `await Get()` within it somehow!
    if output_format == ListOptions.OutputFormat.provides:
        # To get provides clauses, we need hydrated targets.
        collection = await Get[HydratedTargets](Addresses, addresses)
        print_fn = _make_provides_print_fn(provides_columns)
    elif output_format == ListOptions.OutputFormat.documented:
        # To get documentation, we need hydrated targets.
        collection = await Get[HydratedTargets](Addresses, addresses)
        print_fn = _print_documented_target
    elif output_format == ListOptions.OutputFormat.json:
        # To get fingerprints of each target and its dependencies, we have to request that information
        # specifically.
        collection = await Get[FingerprintedTargetCollection](Addresses, addresses)
        print_fn = _print_fingerprinted_target
    else:
        assert output_format == ListOptions.OutputFormat.address_specs
        # Otherwise, we can use only addresses.
        collection = addresses
        print_fn = lambda address: address.spec

    with list_options.line_oriented(console) as print_stdout:
        if not collection.dependencies:
            console.print_stderr("WARNING: No targets were matched in goal `{}`.".format("list"))

        for item in collection:
            result = print_fn(item)
            if result:
                print_stdout(result)

    return List(exit_code=0)


def rules():
    return [list_targets]
