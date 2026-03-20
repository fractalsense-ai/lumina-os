---
version: 1.0.0
last_updated: 2026-03-20
---

# API Server Architecture

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-18  

---

This document describes the internal structure of the Lumina API server after its decomposition from a monolithic single-file implementation into a thin factory plus dedicated sub-modules.

---

## A. Motivation

The original `server.py` grew to ~3,600 lines as the system acquired new capabilities: multi-domain routing, HITL admin staging, ingestion pipeline, night-cycle scheduling, governance dashboard, cross-domain synthesis, and System Log record browsing. At that scale:

- **Tests required full-import** of the entire module to patch any single function, making fixture setup slow and interdependencies fragile.
- **Merge conflicts were frequent** — unrelated features touched the same file.
- **Responsibility boundaries were invisible** — session state, LLM dispatch, route handlers, and Pydantic models were all co-located.

The refactor replaces the monolith with a ~200-line app factory that assembles routers from 22 focused sub-modules.

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
└── routes/
    ├── chat.py          ← POST /api/chat
    ├── auth.py          ← auth and user-management endpoints
    ├── admin.py         ← escalation, audit, manifest, HITL admin-command endpoints
    ├── ctl.py           ← System Log record-browsing endpoints
    ├── domain.py        ← domain-pack lifecycle and session-close endpoints
    ├── ingestion.py     ← document ingestion pipeline endpoints
    ├── system.py        ← health, domain listing, tool adapter, System Log validate
    ├── dashboard.py     ← governance dashboard telemetry endpoints
    └── nightcycle.py    ← night-cycle trigger, status, and proposal endpoints
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

## SEE ALSO

[lumina-api-server(2)](../2-syscalls/lumina-api-server.md), [session-management](../3-functions/session.md), [domain-adapter-pattern](domain-adapter-pattern.md)
