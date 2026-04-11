---
section: 7
title: Microservice Boundaries
version: 1.0.0
last_updated: 2026-04-11
---

# Microservice Boundaries

## Overview

Project Lumina decomposes from a monolith with modular routers into bounded
services, each ownable and independently runnable.  During development every
service is mounted on the **gateway** (the former `server.py`) so a single
`uvicorn` process still serves the full API.  In production each service
*may* be extracted to its own process behind a reverse-proxy.

### Design Principles

| Principle | Rule |
|-----------|------|
| **Shared nothing** | Each service owns its persistence adapter; cross-service reads go through HTTP |
| **Token validation is local** | Every service embeds JWT verification using the three track secrets (see `parallel-authority-tracks.md`) |
| **Events over calls** | Writes to the System Log flow through the log bus; services subscribe, not poll |
| **The gateway is thin** | It mounts sub-applications and manages CORS/in-flight counting — zero business logic |
| **Tests are portable** | Each service exposes a `create_app()` factory; tests can instantiate a single service or the full gateway |

---

## Service Inventory

### 1. Auth Service

| Attribute | Value |
|-----------|-------|
| **Package** | `src/lumina/services/auth/` |
| **Owns** | user registration, login, token issuance/refresh, invite/onboarding, user CRUD, password reset, token revocation |
| **Persistence** | user store (profiles), credential store (password hashes) |
| **JWT tracks** | Issues tokens for all three tracks; owns all three signing secrets |

**Endpoints**

| Method | Path | Auth Track | Notes |
|--------|------|------------|-------|
| POST | `/api/auth/register` | none (bootstrap) | First user becomes root |
| POST | `/api/auth/login` | none → user | Rejects admin/domain track roles |
| GET | `/api/auth/guest-token` | none → user | Ephemeral guest token |
| POST | `/api/auth/refresh` | user | |
| GET | `/api/auth/me` | user | |
| GET | `/api/auth/users` | user (root) | List all users |
| PATCH | `/api/auth/users/{user_id}` | user (root) | Update role / governed_modules |
| DELETE | `/api/auth/users/{user_id}` | user (root) | Deactivate |
| POST | `/api/auth/revoke` | user | Revoke own token |
| POST | `/api/auth/password-reset` | user | Change own password |
| POST | `/api/auth/invite` | user (root/it_support) | Generate invite token |
| POST | `/api/auth/setup-password` | none → scoped | Activate invited account |
| POST | `/api/admin/auth/login` | none → admin | System-track login |
| POST | `/api/admin/auth/refresh` | admin | |
| GET | `/api/admin/auth/me` | admin | |
| POST | `/api/domain/auth/login` | none → domain | Domain-track login |
| POST | `/api/domain/auth/refresh` | domain | |
| GET | `/api/domain/auth/me` | domain | |

**Source routes:** `routes/auth.py`, `routes/admin_auth.py`

---

### 2. System Log Service

| Attribute | Value |
|-----------|-------|
| **Package** | `src/lumina/services/system_log/` |
| **Owns** | append-only log, hash-chain validation, SSE event streaming, audit queries, warning/alert stores |
| **Persistence** | log records, sessions index, hash chain, warning/alert stores |
| **Internal** | `log_bus` (async event queue), `log_router` (level-based routing) |

**Endpoints**

| Method | Path | Auth Track | Notes |
|--------|------|------------|-------|
| GET | `/api/system-log/records` | user (root/qa/auditor) | Query log records |
| GET | `/api/system-log/sessions` | user (root/qa/auditor) | List log sessions |
| GET | `/api/system-log/records/{record_id}` | user (root/qa/auditor) | Single record |
| GET | `/api/system-log/warnings` | user (root/qa/auditor) | |
| GET | `/api/system-log/alerts` | user (root/qa/auditor) | |
| GET | `/api/system-log/validate` | any (root/da/qa/auditor) | Hash-chain validation |
| GET | `/api/audit/log` | any | Scoped by role |
| GET | `/api/events/token` | user | SSE token |
| GET | `/api/events/stream` | SSE token | Server-sent events |

**Source routes:** `routes/system_log.py`, `routes/events.py`, audit portion of `routes/admin.py`, validation from `routes/system.py`

---

### 3. Ingestion Service

| Attribute | Value |
|-----------|-------|
| **Package** | `src/lumina/services/ingestion/` |
| **Owns** | file upload, content extraction, staged review workflow, commit to domain packs |
| **Persistence** | ingestion records, staged files, staging area (`data/staging/`) |

**Endpoints**

| Method | Path | Auth Track | Notes |
|--------|------|------------|-------|
| POST | `/api/ingest/upload` | user (root/da) | Upload document |
| GET | `/api/ingest` | user | List ingestions |
| GET | `/api/ingest/{ingestion_id}` | user | Single ingestion |
| POST | `/api/ingest/{ingestion_id}/extract` | user (root/da) | Run extraction |
| POST | `/api/ingest/{ingestion_id}/review` | user (root/da) | Submit review |
| POST | `/api/ingest/{ingestion_id}/commit` | user (root/da) | Commit to domain |
| POST | `/api/staging/create` | user (root/da) | Create staged file |
| GET | `/api/staging/pending` | user (root/da) | List pending files |
| GET | `/api/staging/{staged_id}` | user (root/da) | Staged file details |
| POST | `/api/staging/{staged_id}/approve` | user (root) | Approve staged file |
| POST | `/api/staging/{staged_id}/reject` | user (root/da) | Reject staged file |

**Source routes:** `routes/ingestion.py`, `routes/staging.py`

---

### 4. Domain Authority Service

| Attribute | Value |
|-----------|-------|
| **Package** | `src/lumina/services/domain/` |
| **Owns** | domain pack lifecycle, physics authoring, domain role assignment, domain-scoped sessions |
| **Persistence** | domain pack configs, physics files, domain role assignments |
| **JWT track** | Primarily domain-track; root cross-track access allowed |

**Endpoints**

| Method | Path | Auth Track | Notes |
|--------|------|------------|-------|
| POST | `/api/domain-pack/commit` | domain/admin (root/da) | Commit domain pack changes |
| GET | `/api/domain-pack/{domain_id}/history` | any (root/da/qa/auditor) | Pack commit history |
| PATCH | `/api/domain-pack/{domain_id}/physics` | domain/admin (root/da) | Update domain physics |
| GET | `/api/domain-pack/{domain_id}/sessions` | any (root/da/qa/auditor) | List domain sessions |
| POST | `/api/domain-pack/{domain_id}/commit` | domain/admin (root/da) | Close and commit session |
| GET | `/api/domain-roles/defaults` | any | List default roles |
| GET | `/api/domain-roles/{module_id}` | any | Get module roles |
| POST | `/api/domain-roles/{module_id}/assign` | domain/admin (root/da) | Assign domain role |
| DELETE | `/api/domain-roles/{module_id}/{user_id}` | domain/admin (root/da) | Revoke domain role |

**Source routes:** `routes/domain.py`, `routes/domain_roles.py`

---

### 5. Admin & Escalation Service

| Attribute | Value |
|-----------|-------|
| **Package** | `src/lumina/services/admin/` |
| **Owns** | escalation lifecycle, admin command pipeline (SLM-assisted), manifest integrity, session unlock |
| **Persistence** | escalation queue, staged commands, manifest hashes |
| **Internal** | `routes/ops/` — 8 operation handler modules dispatched by admin command |

**Endpoints**

| Method | Path | Auth Track | Notes |
|--------|------|------------|-------|
| GET | `/api/escalations` | admin (root/it_support/da) | List escalations |
| GET | `/api/escalations/{escalation_id}` | admin (root/it_support) | Detail |
| DELETE | `/api/escalations/stale` | admin (root) | Purge stale |
| POST | `/api/escalations/{escalation_id}/resolve` | admin (root/it_support) | Resolve |
| POST | `/api/admin/command` | admin (root) | Stage admin command |
| GET | `/api/admin/command/staged` | admin (root) | List staged commands |
| POST | `/api/admin/command/{staged_id}/resolve` | admin (root) | Execute staged command |
| GET | `/api/manifest/check` | any | Check manifest integrity |
| POST | `/api/manifest/regen` | admin (root) | Regenerate manifest |
| POST | `/api/sessions/{session_id}/unlock` | admin (root) | Unlock stuck session |

**Source routes:** `routes/admin.py`, `routes/ops/*`

---

### 6. Core Orchestrator

| Attribute | Value |
|-----------|-------|
| **Package** | `src/lumina/services/core/` (or remains at `src/lumina/api/`) |
| **Owns** | chat/session lifecycle, LLM orchestration, tool execution, health, consent, holodeck simulation, domain info |
| **Persistence** | session containers, chat transcripts, consent records |
| **Internal** | `session.py`, `processing.py`, domain-declared route mounting |

**Endpoints**

| Method | Path | Auth Track | Notes |
|--------|------|------------|-------|
| POST | `/api/chat` | user | Main conversation endpoint |
| GET | `/api/health` | none | Health check |
| GET | `/api/health/load` | none | Load metrics |
| GET | `/api/domains` | any | List registered domains |
| GET | `/api/domain-info` | any | Domain detail |
| POST | `/api/tool/{tool_id}` | user | Execute tool |
| POST | `/api/consent/accept` | user | Record consent |
| POST | `/api/holodeck/simulate` | user (root/da) | Run simulation |
| GET | `/api/panels/{panel_id}` | user | Panel data |

**Source routes:** `routes/chat.py`, `routes/system.py`, `routes/consent.py`, `routes/holodeck.py`, `routes/panels.py`

---

### 7. Dashboard Service

| Attribute | Value |
|-----------|-------|
| **Package** | `src/lumina/services/dashboard/` |
| **Owns** | read-only analytics aggregation |
| **Persistence** | none (reads from System Log Service and Core Orchestrator) |

**Endpoints**

| Method | Path | Auth Track | Notes |
|--------|------|------------|-------|
| GET | `/api/dashboard/domains` | user (root/da/qa/auditor) | Domain overview |
| GET | `/api/dashboard/telemetry` | user (root/qa/auditor) | Telemetry summary |

**Source routes:** `routes/dashboard.py`

---

### Daemon Batch & Vocabulary

Daemon batch processing operations (trigger, status, report, proposals, resolve) are
dispatched through `POST /api/admin/command` with the appropriate `operation` field.
See the admin command reference for details. `routes/vocabulary.py` is mounted on the
gateway for metric submission and a growth dashboard.

| Method | Path | Auth Track | Notes |
|--------|------|------------|-------|
| POST | `/api/admin/command` | user (root/da) | Daemon ops via `operation` field |
| POST | `/api/user/{user_id}/vocabulary-metric` | user | Submit vocab metric |
| GET | `/api/dashboard/education/vocabulary-growth` | user (root/da/qa/auditor) | Growth dashboard |

---

## Service-to-Service Communication

### Token Validation

Every service embeds `verify_scoped_jwt()` from `lumina.auth.auth` and
applies its own role checks.  There are no service-to-service tokens —
user/admin/domain tokens flow through the gateway unmodified.

### Event Bus

The **System Log bus** (`lumina.system_log.log_bus`) is the inter-service
event backbone.  Services emit log events by calling the bus directly
(in-process) or via `POST /api/system-log/emit` (future, cross-process).

### Cross-Service Data Access

| Consumer | Provider | Mechanism |
|----------|----------|-----------|
| Admin → Auth | User lookup, role update | HTTP `/api/auth/users` |
| Ingestion → Domain | Pack commit | HTTP `/api/domain-pack/commit` |
| Dashboard → System Log | Log queries | HTTP `/api/system-log/records` |
| Core → Auth | Token validation | Local JWT verify (shared secret) |
| Core → Domain | Runtime context | `DOMAIN_REGISTRY` (in-process) |

### Shared Libraries (not services)

| Library | Location | Used By |
|---------|----------|---------|
| JWT auth | `lumina.auth.auth` | All services |
| Middleware | `lumina.api.middleware` | All services |
| Admin middleware | `lumina.api.admin_middleware` | Admin, Auth |
| Domain middleware | `lumina.api.domain_middleware` | Domain Authority |
| Permissions | `lumina.core.permissions` | Core, Domain, Admin |
| Domain registry | `lumina.core.domain_registry` | Core, Domain, Dashboard |
| Persistence adapter | `lumina.persistence.adapter` | All services (each gets own instance) |

---

## Gateway Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Gateway (server.py)               │
│  CORS · In-flight counter · Domain-declared routes   │
│  Startup: log bus, knowledge index, vector stores,   │
│           SLM worker, resource monitor daemon         │
├────────┬────────┬────────┬────────┬────────┬────────┤
│  Auth  │ SysLog │Ingest  │Domain  │ Admin  │  Core  │
│Service │Service │Service │Service │Service │Orchestr│
└────────┴────────┴────────┴────────┴────────┴────────┘
```

Each service is a FastAPI **sub-application** created by a `create_app()`
factory.  The gateway mounts them at their path prefixes:

```python
from lumina.services.auth.app import create_app as create_auth_app
app.mount("/", create_auth_app(settings))
```

> **Development mode:** All services run in one process.
> **Production mode (future):** Each service runs its own `uvicorn` behind
> a reverse proxy (nginx / Caddy) routing by path prefix.

---

## Extraction Order

| Phase | Service | Depends On | Rationale |
|-------|---------|------------|-----------|
| 2a | Auth | — | Token issuance is the natural first boundary; no deps on other services |
| 2b | System Log | — | Already has own bus + router; append-only log is a textbook microservice |
| 2c | Ingestion | — | Distinct pipeline lifecycle |
| 2d | Domain Authority | Phase 1 ✅ | Parallel track is now architecturally isolated |
| 2e | Admin & Escalation | Auth | Admin commands dispatch through ops modules |
| 2f | Dashboard | System Log | Read-only; pulls from log service |
| 2g | Core Orchestrator | All above | Whatever remains is the core |

Steps 2a–2c are independent and can be done in parallel.

---

## SEE ALSO

- [parallel-authority-tracks.md](parallel-authority-tracks.md) — Three-track JWT model
- [api-server-architecture.md](api-server-architecture.md) — Current monolith architecture
