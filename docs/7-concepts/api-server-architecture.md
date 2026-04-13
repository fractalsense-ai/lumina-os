---
version: 1.1.0
last_updated: 2026-06-15
---

# API Server Architecture

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-06-15  

---

This document describes the internal structure of the Lumina API server after its decomposition from a monolithic single-file implementation into a thin factory plus dedicated sub-modules.

---

## A. Motivation

The original `server.py` grew to ~3,600 lines as the system acquired new capabilities: multi-domain routing, HITL admin staging, ingestion pipeline, daemon batch scheduling, governance dashboard, cross-domain synthesis, and System Log record browsing. At that scale:

- **Tests required full-import** of the entire module to patch any single function, making fixture setup slow and interdependencies fragile.
- **Merge conflicts were frequent** — unrelated features touched the same file.
- **Responsibility boundaries were invisible** — session state, LLM dispatch, route handlers, and Pydantic models were all co-located.

The refactor replaces the monolith with a ~200-line app factory that assembles routers from 22 focused sub-modules.

> **Note:** The frontend has undergone a parallel HMVC decomposition. Domain-specific
> dashboard panels, sidebar components, and client-side services now live in each domain
> pack's `web/` directory and register via the `PluginRegistry`. See
> [`governance-dashboard.md`](governance-dashboard.md) and
> [`hmvc-heritage.md`](hmvc-heritage.md) for details.

---

## B. Module Responsibilities

```
src/lumina/api/
├── server.py            ← thin factory: creates FastAPI app, mounts routers, configures CORS
│                           _ModProxy bridge for test monkey-patching (see §C)
├── config.py            ← env-var singletons: DOMAIN_REGISTRY, PERSISTENCE, feature flags
├── session.py           ← SessionContainer, DomainContext, get_or_create_session
├── models.py            ← Pydantic request/response models
├── middleware.py        ← JWT bearer scheme, get_current_user, require_auth, require_role
├── llm.py               ← call_llm — provider dispatch (OpenAI / Anthropic)
├── processing.py        ← process_message — six-stage per-turn pipeline
├── runtime_helpers.py   ← render_contract_response, invoke_runtime_tool
├── utils/
│   ├── text.py          ← LaTeX regex helpers, strip_latex_delimiters
│   ├── glossary.py      ← detect_glossary_query, per-domain definition cache
│   ├── coercion.py      ← normalize_turn_data, field-type coercers
│   └── templates.py     ← template rendering for tool-call policy strings
└── routes/              ← thin re-export stubs; canonical code in services/
    ├── chat.py          ← POST /api/chat
    ├── auth.py          ← → services/auth/routes.py
    ├── admin.py         ← escalation, audit, manifest, HITL admin-command endpoints
    ├── admin_auth.py    ← → services/auth/admin_routes.py
    ├── system_log.py    ← → services/system_log/routes.py
    ├── domain.py        ← → services/domain/routes.py
    ├── domain_roles.py  ← → services/domain/roles_routes.py
    ├── ingestion.py     ← → services/ingestion/routes.py
    ├── staging.py       ← → services/ingestion/staging_routes.py
    ├── system.py        ← health, domain listing, tool adapter, System Log validate
    ├── dashboard.py     ← → services/dashboard/routes.py
    ├── events.py        ← → services/system_log/events_routes.py
    ├── consent.py       ← POST /api/consent/accept
    ├── holodeck.py      ← POST /api/holodeck/simulate
    ├── panels.py        ← GET/PATCH /api/panels/{panel_id}
    ├── vocabulary.py    ← vocabulary metric submission and growth dashboard
    └── ops/             ← admin command operation handlers (8 modules)

src/lumina/services/     ← canonical service implementations (Phase 2 decomposition)
├── auth/                ← user registration, login, token issuance, invite, CRUD
├── system_log/          ← append-only log, hash-chain, SSE events, warnings, alerts
├── ingestion/           ← file upload, extraction, staging workflow
├── domain/              ← domain pack lifecycle, physics, domain roles
├── dashboard/           ← read-only analytics aggregation
├── admin/               ← escalation lifecycle, admin command pipeline
└── registry.py          ← service discovery metadata
```

### Key invariant

No route module imports from another route module. All shared state is accessed via `lumina.api.config` singletons (`_cfg.PERSISTENCE`, `_cfg.DOMAIN_REGISTRY`). This keeps the dependency graph a strict tree with `config` at the root.

---

## C. `_ModProxy` Test Bridge

Tests need to monkey-patch `PERSISTENCE`, `DOMAIN_REGISTRY`, `slm_available`, and similar singletons. In the monolith these were module-level attributes; after decomposition they live in `config.py` and `lumina.core.slm`. Route handlers read them from those modules at call time.

`_ModProxy` is a `types.ModuleType` subclass registered as `sys.modules["lumina.api.server"]`. Its `__setattr__` intercepts writes to the two propagation sets and forwards them to the canonical home:

```python
class _ModProxy(types.ModuleType):
    _CONFIG_PROPAGATED = frozenset({"PERSISTENCE", "BOOTSTRAP_MODE", "DOMAIN_REGISTRY"})
    _SLM_PROPAGATED    = frozenset({"slm_available", "slm_parse_admin_command"})

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name in self._CONFIG_PROPAGATED:
            import lumina.api.config as _cm; setattr(_cm, name, value)
        if name in self._SLM_PROPAGATED:
            import lumina.core.slm as _sm; setattr(_sm, name, value)
```

This means existing test fixtures that write `app.PERSISTENCE = NullPersistenceAdapter()` continue to work without modification — the write fans out to every module that reads the singleton.

---

## D. Session Multi-Domain Isolation

Sessions are no longer immutably bound to their initial domain. Each session holds a `SessionContainer` whose `contexts` dict maps `domain_id → DomainContext`. On each chat turn:

1. The requested `domain_id` is resolved (explicit → semantic router → default).
2. If no `DomainContext` exists for that domain, one is created and added to `container.contexts`.
3. If `len(container.contexts) >= LUMINA_MAX_CONTEXTS_PER_SESSION` (default 10), the request is rejected with HTTP 429.

Each `DomainContext` carries its own System Log ledger path, conversation history, and evidence state. Contexts within the same session are isolated — they do not share turn history.

---

## E. Glossary Per-Domain Cache

`utils/glossary.py` maintains a module-level `_CACHE` dict keyed by `domain_id`. On the first glossary-query check for a domain, the function loads and parses the domain's glossary from the physics document and stores it in the cache. Subsequent calls for the same domain are O(1) dict lookups.

The cache is invalidated when `PATCH /api/domain-pack/{domain_id}/physics` commits a physics update (the route calls `_invalidate_glossary_cache(domain_id)` exported from `utils/glossary.py`).

---

## F. Performance Profile

The decomposition has no runtime overhead — `server.py` assembles routers at startup, not per-request. Measured gains from the refactor:

| Metric | Before | After |
|--------|--------|-------|
| Full test suite cold-import time | ~4.1 s | ~1.6 s |
| Average fixture setup time | ~320 ms | ~85 ms |
| Lines in `server.py` | 3,658 | ~200 |

---

## G. Dynamic Domain Route Mounting

Domain packs may declare their own HTTP endpoints without touching `src/lumina/`. This
keeps domain-specific routes inside the domain pack — consistent with the HMVC
self-containment contract (see [`hmvc-heritage(7)`](hmvc-heritage.md)).

### Declaration

Each route is declared in the domain's `cfg/runtime-config.yaml` under
`adapters.api_routes`:

```yaml
adapters:
  api_routes:
    post_vocabulary_metric:
      path: /api/user/{user_id}/vocabulary-metric
      method: POST
      module_path: domain-packs/education/controllers/api_handlers.py
      callable: post_vocabulary_metric
      roles: []
      request_body:
        vocabulary_complexity_score: {type: float, ge: 0.0, le: 1.0, required: true}
    dashboard_vocabulary_growth:
      path: /api/dashboard/education/vocabulary-growth
      method: GET
      module_path: domain-packs/education/controllers/api_handlers.py
      callable: dashboard_vocabulary_growth
      roles: [root, domain_authority, teacher]
```

### Loading pipeline

1. **`runtime_loader.py`** — During domain load, the loader iterates
   `adapters_cfg.get("api_routes")`, resolves each `module_path` + `callable` via
   `_load_callable()`, and appends the resulting dict (path, method, handler function,
   roles, request_body schema) to `api_route_defs` in the runtime context.

2. **`server.py` → `_mount_domain_api_routes()`** — At startup (after all domains are
   registered), this function iterates every domain's `api_route_defs` and calls
   `app.add_api_route()` for each entry. The core server wraps every handler with JWT
   authentication and RBAC role enforcement so that domain handlers remain free of any
   `lumina.api.*` imports.

### Handler contract

Domain handlers receive keyword-injected dependencies and return plain dicts:

```python
async def post_vocabulary_metric(
    *,
    user_id: str,
    body: dict[str, Any],
    user_data: dict[str, Any],
    persistence: Any,
    resolve_profile_path: Any,
    **_kw: Any,
) -> dict[str, Any]:
    ...
```

To signal an HTTP error, return `{"__status": 403, "detail": "..."}` — the server wrapper
converts this to an `HTTPException` automatically.

### Key invariant

Domain-declared routes go through the same auth/role middleware as core routes.  A domain
pack cannot bypass `require_auth` or `require_role` — the wrapper enforces the `roles`
list declared in `runtime-config.yaml`.

---

## SEE ALSO

[lumina-api-server(2)](../2-syscalls/lumina-api-server.md), [session-management](../3-functions/session.md), [domain-adapter-pattern](domain-adapter-pattern.md)
