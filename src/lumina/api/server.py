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
from lumina.api.routes.staging import router as staging_router  # noqa: E402
from lumina.api.routes.admin_auth import router as admin_auth_router  # noqa: E402
from lumina.api.routes.events import router as events_router  # noqa: E402
from lumina.api.routes.system import router as system_router  # noqa: E402
from lumina.api.routes.consent import router as consent_router  # noqa: E402
from lumina.api.routes.holodeck import router as holodeck_router  # noqa: E402
from lumina.api.routes.panels import router as panels_router  # noqa: E402

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
# Pure ASGI middleware (avoids BaseHTTPMiddleware deadlock with run_in_threadpool)

from starlette.types import ASGIApp, Receive, Scope, Send


class _InFlightCounterMiddleware:
    """Middleware that tracks in-flight HTTP requests for the daemon."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        from lumina.systools.hw_http_queue import increment, decrement
        increment()
        try:
            await self._app(scope, receive, send)
        finally:
            decrement()


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
app.include_router(staging_router)
app.include_router(admin_auth_router)
app.include_router(admin_router)
app.include_router(events_router)
app.include_router(consent_router)
app.include_router(holodeck_router)
app.include_router(panels_router)


# ─────────────────────────────────────────────────────────────
# Domain-declared API routes — dynamic registration
# ─────────────────────────────────────────────────────────────


def _mount_domain_api_routes() -> int:
    """Iterate all domains, discover api_route_defs, and mount them on *app*.

    Each domain's ``runtime-config.yaml`` may declare ``adapters.api_routes``
    entries.  The runtime loader resolves them into ``api_route_defs`` (list of
    dicts with ``path``, ``method``, ``handler_fn``, ``roles``, etc.).

    The core server wraps each handler with auth + role enforcement so the
    domain handler stays free of FastAPI / middleware imports.

    Returns the number of routes mounted.
    """
    from fastapi import Depends, HTTPException, Request
    from fastapi.security import HTTPAuthorizationCredentials
    from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth, require_role

    mounted = 0
    for domain_info in DOMAIN_REGISTRY.list_domains():
        domain_id = domain_info["domain_id"]
        try:
            ctx = DOMAIN_REGISTRY.get_runtime_context(domain_id)
        except Exception:
            log.warning("domain_api_routes: could not load context for %s", domain_id)
            continue

        route_defs: list = ctx.get("api_route_defs") or []
        for rdef in route_defs:
            _path: str = rdef.get("path", "")
            _method: str = rdef.get("method", "GET")
            _handler_fn = rdef.get("handler_fn")
            _roles: list = rdef.get("roles") or []
            _body_schema: dict = rdef.get("request_body") or {}

            if not _path or not _handler_fn:
                continue

            # Capture in closure
            _fn = _handler_fn
            _r = list(_roles)
            _has_body = bool(_body_schema) and _method in ("POST", "PUT", "PATCH")

            if _method == "POST" and "{user_id}" in _path:
                # POST with path param + body
                async def _endpoint(
                    user_id: str,
                    request: Request,
                    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
                    *,
                    _handler=_fn,
                    _allowed_roles=_r,
                ) -> dict:
                    current = await get_current_user(credentials)
                    user_data = require_auth(current)
                    if _allowed_roles:
                        require_role(user_data, *_allowed_roles)
                    body = await request.json()
                    result = await _handler(
                        user_id=user_id,
                        body=body,
                        user_data=user_data,
                        persistence=_config_module.PERSISTENCE,
                        resolve_profile_path=_resolve_user_profile_path,
                        profiles_dir=_config_module._PROFILES_DIR,
                    )
                    if isinstance(result, dict) and "__status" in result:
                        raise HTTPException(status_code=result["__status"], detail=result.get("detail", ""))
                    return result

            elif _method == "GET":
                async def _endpoint(
                    request: Request,
                    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
                    *,
                    _handler=_fn,
                    _allowed_roles=_r,
                ) -> dict:
                    current = await get_current_user(credentials)
                    user_data = require_auth(current)
                    if _allowed_roles:
                        require_role(user_data, *_allowed_roles)
                    result = await _handler(
                        user_data=user_data,
                        persistence=_config_module.PERSISTENCE,
                        resolve_profile_path=_resolve_user_profile_path,
                        profiles_dir=_config_module._PROFILES_DIR,
                    )
                    if isinstance(result, dict) and "__status" in result:
                        raise HTTPException(status_code=result["__status"], detail=result.get("detail", ""))
                    return result

            else:
                log.warning("domain_api_routes: unsupported method %s for %s", _method, _path)
                continue

            app.add_api_route(_path, _endpoint, methods=[_method])
            mounted += 1
            log.info("domain_api_routes: mounted %s %s", _method, _path)

    return mounted


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
    from lumina.core.invite_store import register_persistence as _reg_invite_persistence
    _reg_invite_persistence(PERSISTENCE)

    _assert_system_physics_commitment()

    # ── Mount domain-declared API routes ──────────────────────
    try:
        _n_routes = _mount_domain_api_routes()
        if _n_routes:
            log.info("Domain API routes: %d route(s) mounted", _n_routes)
    except Exception:
        log.warning("Domain API route registration failed", exc_info=True)

    # ── Seal diagnostic: surface missing secrets early ────────
    _seal_secret = os.environ.get("LUMINA_TRANSCRIPT_HMAC_SECRET") or os.environ.get("LUMINA_JWT_SECRET")
    if _seal_secret:
        log.info("Transcript seal: configured (chat persistence enabled)")
    else:
        log.warning("Transcript seal: NOT CONFIGURED — set LUMINA_JWT_SECRET or LUMINA_TRANSCRIPT_HMAC_SECRET for chat persistence")

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

    # Load persisted MiniLM vector stores for RAG grounding + domain routing.
    try:
        from lumina.retrieval.housekeeper import make_registry as _make_vsr
        from lumina.retrieval.embedder import DocEmbedder as _DocEmbedder
        from lumina.core.nlp import set_vector_registry as _set_vr

        _vsr = _make_vsr()
        _vsr.load_all()

        # Bootstrap: if any registered domain is missing a persisted vector
        # store, build all indexes now.  This mirrors the KnowledgeIndex
        # pattern above — runs once on first startup, subsequent starts
        # find the persisted stores and skip.
        _persisted_domains = set(_vsr.domain_ids())
        _registered_domains = {d["domain_id"] for d in DOMAIN_REGISTRY.list_domains()}
        _missing = _registered_domains - _persisted_domains
        if _missing:
            log.info(
                "VectorStore bootstrap: %d domain(s) missing (%s) — rebuilding all indexes",
                len(_missing), ", ".join(sorted(_missing)),
            )
            try:
                from lumina.retrieval.housekeeper import rebuild_all_domain_indexes as _rebuild_all
                _embedder = _DocEmbedder()
                _rebuild_summary = _rebuild_all(_vsr, _embedder)
                log.info(
                    "VectorStore bootstrap complete: %d domains, %d total chunks in %.1fs",
                    _rebuild_summary.get("domains_rebuilt", 0),
                    _rebuild_summary.get("total_chunks", 0),
                    _rebuild_summary.get("elapsed_seconds", 0),
                )
            except Exception:
                log.warning("VectorStore bootstrap failed — RAG grounding may be degraded", exc_info=True)

        _emb = _DocEmbedder()
        _set_vr(_vsr, _emb)
        log.info("VectorStoreRegistry active: %d domain store(s) loaded", len(_vsr._stores))
        log.info(
            "Embedding provider: %s  model: %s  endpoint: %s",
            _emb._provider,
            _emb._model_name,
            _emb._endpoint if _emb._provider == "ollama" else "(local)",
        )
    except Exception:
        log.warning("VectorStoreRegistry: not loaded — retrieval extra may not be installed", exc_info=True)

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
        _cfg_path = _REPO_ROOT / "domain-packs" / "system" / "cfg" / "runtime-config.yaml"
        if _cfg_path.exists():
            _raw = _load_yaml(_cfg_path)
            daemon_cfg = _raw.get("daemon", {})
    except Exception:
        log.warning("Could not load daemon config from runtime-config.yaml")

    if daemon_cfg.get("enabled", False):
        estimator = LoadEstimator(
            weights=daemon_cfg.get("probe_weights"),
            idle_threshold=daemon_cfg.get("idle_threshold", 0.20),
            window_depth=daemon_cfg.get("telemetry_window_depth", 20),
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
