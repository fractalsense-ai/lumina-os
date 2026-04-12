from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _mount_domain_routes_if_loaded(request):
    """Ensure domain-declared API routes are available during tests.

    The domain routes are normally mounted by an ``on_event("startup")``
    handler, but many test suites create a ``TestClient`` without
    triggering the startup lifecycle.  This fixture calls
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
