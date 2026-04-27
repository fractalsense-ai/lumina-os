"""_domain_pack_loader — Internal helper for loading modules from domain packs.

Centralises the importlib.util.spec_from_file_location() pattern used by
compatibility shims in lumina.systools, lumina.lib, and lumina.tools.  These
shims re-export public APIs from the canonical copies that now live under
model-packs/system/.

This module is not part of the public API.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def load_domain_pack_module(rel_path: str, module_key: str | None = None):
    """Load a Python module from a domain-pack-relative *rel_path*.

    Parameters
    ----------
    rel_path:
        Path relative to the repository root, e.g.
        ``"model-packs/system/domain-lib/sensors/hw_disk.py"``.
    module_key:
        Key to register in ``sys.modules``.  Defaults to a mangled version
        of *rel_path* to avoid collisions with regular package imports.

    Returns
    -------
    types.ModuleType
        The loaded module object.
    """
    if module_key is None:
        module_key = "dp_" + rel_path.replace("/", "_").replace("\\", "_").replace(".py", "")

    if module_key in sys.modules:
        return sys.modules[module_key]

    abs_path = _REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(module_key, str(abs_path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod
