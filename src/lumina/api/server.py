"""
lumina-api-server.py — Project Lumina Integration Server

Generic runtime host for D.S.A. orchestration:
- Loads runtime behavior from domain-owned config
- Keeps core server free of domain-specific prompt/state logic
- Routes each turn through orchestrator prompt contracts and System Log

Architecture: thin app factory that assembles routers from sub-modules.
All business logic lives in dedicated modules under lumina.api.*.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import sys
import types
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


class _ModProxy(types.ModuleType):
    """Module subclass that propagates singleton writes to the config module.

    Tests monkey-patch ``mod.PERSISTENCE = NullPersistenceAdapter()`` etc.
    Routes read singletons via ``_cfg.PERSISTENCE`` (attribute access on the
    config module).  This bridge ensures the two stay in sync.

    Also propagates ``slm_available`` / ``slm_parse_admin_command`` patches
    to the underlying ``lumina.core.slm`` module so that route handlers
    (which read from the slm module at call time) see the patched values.
    """

    _CONFIG_PROPAGATED = frozenset({"PERSISTENCE", "BOOTSTRAP_MODE", "DOMAIN_REGISTRY"})
    _SLM_PROPAGATED = frozenset({"slm_available", "slm_parse_admin_command"})

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name in self._CONFIG_PROPAGATED:
            import lumina.api.config as _cm

            setattr(_cm, name, value)
        if name in self._SLM_PROPAGATED:
            import lumina.core.slm as _sm

            setattr(_sm, name, value)

# ─────────────────────────────────────────────────────────────
# Logging (must precede config imports for log references)
# ─────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("lumina-api")

# ─────────────────────────────────────────────────────────────
# Configuration singletons (re-exported for backward compat)
# ─────────────────────────────────────────────────────────────

from lumina.api.config import (  # noqa: E402
    BOOTSTRAP_MODE,
    CORS_ORIGINS,
    LOG_DIR,
    DOMAIN_REGISTRY,
    DOMAIN_REGISTRY_PATH,
    LLM_PROVIDER,
    PERSISTENCE,
    RUNTIME_CONFIG_PATH,
    SESSION_IDLE_TIMEOUT_MINUTES,
    SYSTEM_PHYSICS_HASH,
    _REPO_ROOT,
    _canonical_sha256,
    _ensure_user_profile,
    _resolve_user_profile_path,
)

import lumina.api.config as _config_module  # noqa: E402

# ─────────────────────────────────────────────────────────────
# Session management (re-exported for backward compat)
# ─────────────────────────────────────────────────────────────

from lumina.api.session import (  # noqa: E402
    _assert_system_physics_commitment,
    _close_session,
    _session_containers,
    get_or_create_session,
)

# ─────────────────────────────────────────────────────────────
# Utility re-exports (tests access these via mod.*)
# ─────────────────────────────────────────────────────────────

from lumina.api.utils.text import _strip_latex_delimiters  # noqa: E402, F401
from lumina.api.utils.glossary import _detect_glossary_query  # noqa: E402, F401
from lumina.api.utils.coercion import (  # noqa: E402, F401
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_str,
    _normalize_turn_data,
)

# ─────────────────────────────────────────────────────────────
# Core message processing (re-exported for backward compat)
# ─────────────────────────────────────────────────────────────

from lumina.api.processing import process_message  # noqa: E402, F401

# SLM re-exports (tests patch these via api_module)
from lumina.core.slm import slm_available, slm_parse_admin_command  # noqa: E402, F401

# ─────────────────────────────────────────────────────────────
# Route modules
# ─────────────────────────────────────────────────────────────

from lumina.api.routes.admin import (  # noqa: E402
    _STAGED_COMMANDS,
    _STAGED_COMMANDS_LOCK,
    router as admin_router,
)
from lumina.api.routes.auth import router as auth_router  # noqa: E402
from lumina.api.routes.chat import router as chat_router  # noqa: E402
from lumina.api.routes.system_log import router as system_log_router  # noqa: E402
from lumina.api.routes.dashboard import router as dashboard_router  # noqa: E402
from lumina.api.routes.domain import router as domain_router  # noqa: E402
from lumina.api.routes.domain_roles import router as domain_roles_router  # noqa: E402
from lumina.api.routes.ingestion import (  # noqa: E402
    _detect_content_type,
    router as ingestion_router,
)
from lumina.api.routes.nightcycle import router as nightcycle_router  # noqa: E402
from lumina.api.routes.staging import router as staging_router  # noqa: E402
from lumina.api.routes.admin_auth import router as admin_auth_router  # noqa: E402
from lumina.api.routes.events import router as events_router  # noqa: E402
from lumina.api.routes.system import router as system_router  # noqa: E402
from lumina.api.routes.consent import router as consent_router  # noqa: E402
from lumina.api.routes.holodeck import router as holodeck_router  # noqa: E402

# ─────────────────────────────────────────────────────────────
# FastAPI Application
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Project Lumina API",
    description="D.S.A. Orchestrator + LLM Conversational Interface (multi-domain)",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── In-flight request counting middleware ──────────────────────

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class _InFlightCounterMiddleware(BaseHTTPMiddleware):
    """Middleware that tracks in-flight HTTP requests for the daemon."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:  # type: ignore[override]
        from lumina.systools.hw_http_queue import increment, decrement
        increment()
        try:
            response = await call_next(request)
        finally:
            decrement()
        return response


app.add_middleware(_InFlightCounterMiddleware)

# Register route groups
app.include_router(chat_router)
app.include_router(auth_router)
app.include_router(system_router)
app.include_router(domain_router)
app.include_router(domain_roles_router)
app.include_router(ingestion_router)
app.include_router(system_log_router)
app.include_router(dashboard_router)
app.include_router(nightcycle_router)
app.include_router(staging_router)
app.include_router(admin_auth_router)
app.include_router(admin_router)
app.include_router(events_router)
app.include_router(consent_router)
app.include_router(holodeck_router)


# ─────────────────────────────────────────────────────────────
# Session Idle Timeout — Background Task
# ─────────────────────────────────────────────────────────────


async def _session_idle_cleanup() -> None:
    """Background task: close sessions that exceed the idle timeout."""
    while True:
        await asyncio.sleep(60)
        if SESSION_IDLE_TIMEOUT_MINUTES <= 0:
            continue
        timeout_seconds = SESSION_IDLE_TIMEOUT_MINUTES * 60
        now = time.time()
        expired_ids = [
            sid for sid, container in _session_containers.items()
            if (now - container.last_activity) > timeout_seconds
        ]
        for sid in expired_ids:
            log.info("Auto-closing idle session: %s", sid)
            try:
                _close_session(sid, "system", "system", "forced", "idle_timeout")
            except Exception:
                log.exception("Failed to auto-close session %s", sid)


@app.on_event("startup")
async def _start_idle_cleanup() -> None:
    _assert_system_physics_commitment()
    if SESSION_IDLE_TIMEOUT_MINUTES > 0:
        asyncio.create_task(_session_idle_cleanup())
        log.info("Session idle timeout enabled: %d minutes", SESSION_IDLE_TIMEOUT_MINUTES)

    # Start the log bus and micro-router before anything else emits events.
    from lumina.system_log import log_bus as _log_bus
    from lumina.system_log import log_router as _log_router
    _log_router.start()
    await _log_bus.start()

    # Build the global KnowledgeIndex (glossary routing + concept graph).
    from lumina.core.knowledge_index import KnowledgeIndex
    from lumina.core.nlp import set_knowledge_index as _set_ki

    _ki = KnowledgeIndex()
    _ki_dir = _REPO_ROOT / "data" / "knowledge-index"
    if not _ki.load(_ki_dir):
        # No persisted index — build from current registry
        try:
            _domain_contexts: dict = {}
            for _d in DOMAIN_REGISTRY.list_domains():
                _did = _d["domain_id"]
                try:
                    _domain_contexts[_did] = DOMAIN_REGISTRY.get_runtime_context(_did)
                except Exception:
                    log.warning("KnowledgeIndex: could not load context for %s", _did)
            if _domain_contexts:
                _ki.build(_domain_contexts)
                _ki.save(_ki_dir)
        except Exception:
            log.warning("KnowledgeIndex: initial build failed — glossary routing unavailable")
    _set_ki(_ki)
    log.info("KnowledgeIndex active: %s", _ki.stats)

    # Start the async SLM PPA enrichment worker ("same bus, different lane").
    from lumina.core.slm_ppa_worker import start as _start_slm_ppa_worker
    await _start_slm_ppa_worker()

    # Start the Resource Monitor Daemon (load-based task scheduling).
    from lumina.daemon import resource_monitor as _resource_monitor
    from lumina.daemon.load_estimator import LoadEstimator
    from lumina.daemon.task_adapter import run_task_preemptible
    from lumina.core.yaml_loader import load_yaml as _load_yaml
    import functools

    daemon_cfg: dict = {}
    try:
        _cfg_path = _REPO_ROOT / "cfg" / "system-runtime-config.yaml"
        if _cfg_path.exists():
            _raw = _load_yaml(_cfg_path)
            daemon_cfg = _raw.get("daemon", {})
    except Exception:
        log.warning("Could not load daemon config from system-runtime-config.yaml")

    if daemon_cfg.get("enabled", False):
        estimator = LoadEstimator(
            weights=daemon_cfg.get("probe_weights"),
            idle_threshold=daemon_cfg.get("idle_threshold", 0.20),
        )
        runner = functools.partial(
            run_task_preemptible,
            domain_loader=getattr(DOMAIN_REGISTRY, "load_all_domain_contexts", None),
            persistence=PERSISTENCE,
        )
        _resource_monitor.init(
            estimator=estimator,
            task_runner=runner,
            config=daemon_cfg,
        )
        await _resource_monitor.start()


@app.on_event("shutdown")
async def _stop_background_tasks() -> None:
    # Stop the daemon before the SLM worker so in-flight tasks drain.
    from lumina.daemon import resource_monitor as _resource_monitor
    await _resource_monitor.stop()

    from lumina.core.slm_ppa_worker import stop as _stop_slm_ppa_worker
    await _stop_slm_ppa_worker()

    # Stop the log bus after workers so in-flight events are still delivered.
    from lumina.system_log import log_bus as _log_bus
    from lumina.system_log import log_router as _log_router
    await _log_bus.stop()
    _log_router.stop()

    log.info("Background tasks stopped")


# ─────────────────────────────────────────────────────────────
# Singleton propagation: allow test monkey-patching of PERSISTENCE etc.
# ─────────────────────────────────────────────────────────────

sys.modules[__name__].__class__ = _ModProxy


# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("LUMINA_PORT", "8000"))
    log.info("Starting Lumina API on port %s | LLM: %s", port, LLM_PROVIDER)
    if DOMAIN_REGISTRY.is_multi_domain:
        log.info("Multi-domain mode: %d domain(s)", len(DOMAIN_REGISTRY.list_domains()))
        for d in DOMAIN_REGISTRY.list_domains():
            log.info("  Domain: %s (%s)%s", d["domain_id"], d["label"], " [default]" if d["is_default"] else "")
    else:
        log.info("Single-domain mode: %s", RUNTIME_CONFIG_PATH)
    log.info("System Log directory: %s", LOG_DIR)
    log.info("Bootstrap mode: %s", BOOTSTRAP_MODE)
    log.info("CORS origins: %s", CORS_ORIGINS)
    uvicorn.run(app, host="0.0.0.0", port=port)
