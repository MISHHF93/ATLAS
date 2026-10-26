"""Import aliases for packages moved under ``atlas.ai`` (streamline pass 3).

``atlas.models.*`` and ``atlas.intel.*`` resolve to the *same module objects* as
``atlas.ai.models.*`` / ``atlas.ai.intel.*`` so old imports, ``mock.patch`` targets
and pickles keep working with no duplicate module state.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys

# Most specific first. Shared type primitives live in neutral ``atlas.schemas`` so the
# control plane never has to load ``atlas.ai`` (see tests/test_import_boundaries.py).
ALIASES: dict[str, str] = {
    "atlas.models.schemas": "atlas.schemas",
    "atlas.ai.models.schemas": "atlas.schemas",
    "atlas.models": "atlas.ai.models",
    "atlas.intel": "atlas.ai.intel",
    "atlas.ml": "atlas.ai.ml",
}


def canonical(name: str) -> str | None:
    for old, new in ALIASES.items():
        if name == old or name.startswith(old + "."):
            mapped = new + name[len(old):]
            return None if mapped == name else mapped
    return None


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, target: str) -> None:
        self.target = target
        self._real_spec = None

    def create_module(self, spec):
        module = importlib.import_module(self.target)
        self._real_spec = module.__spec__
        return module

    def exec_module(self, module) -> None:
        # the import system stamped the alias spec on the real module; restore it
        module.__spec__ = self._real_spec


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        new = canonical(fullname)
        if new is None:
            return None
        if new in sys.modules:
            pass
        elif importlib.util.find_spec(new) is None:
            return None
        loader = _AliasLoader(new)
        real = importlib.util.find_spec(new)
        return importlib.util.spec_from_loader(fullname, loader, is_package=real is not None and real.submodule_search_locations is not None)


def install() -> None:
    if not any(isinstance(f, _AliasFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _AliasFinder())
