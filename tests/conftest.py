from __future__ import annotations

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def merge_module_config_sidecars(module_map: dict) -> dict:
    """Merge module-config.yaml sidecars into raw module_map entries.

    Replicates the runtime-loader auto-discovery so tests that read
    runtime-config.yaml directly see the full merged configuration.
    Inline keys always win (same semantics as the loader).
    """
    for _mod_cfg in module_map.values():
        _mod_dir = _mod_cfg.get("module_path")
        if _mod_dir:
            _mc_path = REPO_ROOT / _mod_dir / "module-config.yaml"
            if _mc_path.is_file():
                with open(_mc_path, encoding="utf-8") as f:
                    _mc = yaml.safe_load(f)
                if isinstance(_mc, dict):
                    for _k, _v in _mc.items():
                        if _k not in _mod_cfg:
                            _mod_cfg[_k] = _v
    return module_map


@pytest.fixture(autouse=True)
def _mount_domain_routes_if_loaded(request):
    """Ensure domain-declared API routes are available during tests.

    The domain routes are normally mounted by the FastAPI lifespan
    startup handler, but many test suites create a ``TestClient`` without
    entering the application lifecycle.  This fixture calls
    ``_mount_domain_api_routes()`` automatically when an ``api_module``
    fixture is in scope.
    """
    api_module = request.fixturenames
    if "api_module" not in api_module:
        return
    # Resolve the fixture (only works when the fixture is actually declared).
    try:
        mod = request.getfixturevalue("api_module")
    except pytest.FixtureLookupError:
        return
    mount_fn = getattr(mod, "_mount_domain_api_routes", None)
    if mount_fn is not None:
        mount_fn()
