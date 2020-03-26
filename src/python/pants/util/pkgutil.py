# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from types import ModuleType
from typing import Tuple

from pkg_resources import DefaultProvider, ZipProvider, get_provider


def module_basename_dirname(module_path: str) -> Tuple[str, str]:
    """Return the import path for the parent module of `module_path`."""
    elements = module_path.split(".")
    dirname = ".".join(elements[:-1])
    basename = elements[-1]
    return (dirname, basename)


def get_resource_bytes(module_path: str, relpath: Path) -> bytes:
    """Extract the bytes of a python source or resource file from the specified moule."""
    provider = get_provider(module_path)
    if not isinstance(provider, DefaultProvider):
        mod = __import__(module_path, fromlist=['ignore'])
        provider = ZipProvider(mod)
    return provider.get_resource_string(module_path, str(relpath))


def get_own_python_source_file_bytes(module_path: str) -> bytes:
    """Extract the bytes of a python source file by its module import name."""
    parent_module, rel_path = module_basename_dirname(module_path)
    return get_resource_bytes(parent_module, Path(f'{rel_path}.py'))
