"""Service registry — maps service names to their standalone entry points.

During development, ``server.py`` (the gateway) imports routers via the thin
re-export stubs under ``lumina.api.routes``.  This registry provides metadata
for tooling, documentation, and future reverse-proxy configuration.

Each entry describes one extractable service:
  - ``package``   — Python import path for the service package
  - ``app``       — import path for the standalone FastAPI app instance
  - ``port``      — default standalone port
  - ``routers``   — list of re-export stub modules under ``lumina.api.routes``
"""

from __future__ import annotations

SERVICES: dict[str, dict] = {
    "auth": {
        "package": "lumina.services.auth",
        "app": "lumina.services.auth.app:app",
        "port": 8001,
        "routers": ["auth", "admin_auth"],
    },
    "system_log": {
        "package": "lumina.services.system_log",
        "app": "lumina.services.system_log.app:app",
        "port": 8002,
        "routers": ["system_log", "events"],
    },
    "ingestion": {
        "package": "lumina.services.ingestion",
        "app": "lumina.services.ingestion.app:app",
        "port": 8003,
        "routers": ["ingestion", "staging"],
    },
    "domain": {
        "package": "lumina.services.domain",
        "app": "lumina.services.domain.app:app",
        "port": 8004,
        "routers": ["domain", "domain_roles"],
    },
    "dashboard": {
        "package": "lumina.services.dashboard",
        "app": "lumina.services.dashboard.app:app",
        "port": 8005,
        "routers": ["dashboard"],
    },
    "admin": {
        "package": "lumina.services.admin",
        "app": "lumina.services.admin.app:app",
        "port": 8006,
        "routers": ["admin"],
        "note": "Reverse re-export: service delegates to lumina.api.routes.admin (mock-target stability)",
    },
}

# Core orchestrator routes — remain in lumina.api.routes, not extracted.
CORE_ROUTES: list[str] = [
    "chat",
    "consent",
    "holodeck",
    "nightcycle",
    "panels",
    "system",
    "vocabulary",
]
