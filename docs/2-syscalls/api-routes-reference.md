---
section: 2
title: API Routes Reference
version: 1.0.0
last_updated: 2026-04-11
---

# API Routes Reference

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-04-11

---

Complete reference for every HTTP endpoint exposed by the Project Lumina API gateway.
Routes are organized by service boundary (see [microservice-boundaries](../7-concepts/microservice-boundaries.md)).
Each entry lists the auth track, required roles, request/response shape, and error codes.

For background on the three-track JWT model, see [parallel-authority-tracks](../7-concepts/parallel-authority-tracks.md).

---

## Auth Track Legend

| Symbol | Meaning |
|--------|---------|
| **system** | Requires `LUMINA_ADMIN_JWT_SECRET`-signed token (`iss: lumina-admin`). Roles: `root`, `super_admin` |
| **domain** | Requires `LUMINA_DOMAIN_JWT_SECRET`-signed token (`iss: lumina-domain`). Roles: `admin` |
| **user** | Requires `LUMINA_USER_JWT_SECRET`-signed token (`iss: lumina-user`). Roles: `user`, `operator`, `half_operator`, `guest` |
| **any** | Any valid token from any track |
| **none** | No authentication required |
| **sse** | SSE token issued by `/api/events/token` (query parameter, not Bearer header) |

---

## 1. Auth Service

**Package:** `src/lumina/services/auth/`
**Source routes:** `routes/auth.py` → `services/auth/routes.py`, `routes/admin_auth.py` → `services/auth/admin_routes.py`

### User-Track Auth

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/auth/register` | none | — | Register new user; first user auto-promoted to `root` in bootstrap mode |
| POST | `/api/auth/login` | none → user | — | Authenticate with username/password; rejects admin/domain-track roles |
| GET | `/api/auth/guest-token` | none → user | — | Issue ephemeral guest JWT (30 min TTL) |
| POST | `/api/auth/refresh` | user | any | Refresh current token |
| GET | `/api/auth/me` | user | any | Current user profile |
| GET | `/api/auth/users` | user | root, super_admin | List all users |
| PATCH | `/api/auth/users/{user_id}` | user | root | Update role / governed_modules |
| DELETE | `/api/auth/users/{user_id}` | user | root | Deactivate user |
| POST | `/api/auth/revoke` | user | any | Revoke own token |
| POST | `/api/auth/password-reset` | user | any | Reset password (root: any user; others: self only) |
| POST | `/api/auth/invite` | user | root, super_admin | Create pending user + invite link |
| POST | `/api/auth/setup-password` | none | — | Activate pending account via invite token |

#### POST `/api/auth/register`

**Request:** `{username, password, role?, governed_modules?}`
**Response:** `{access_token, token_type, user_id, role}`
**Errors:** 400 (missing fields, password < 8 chars), 409 (username taken)

#### POST `/api/auth/login`

**Request:** `{username, password}`
**Response:** `{access_token, token_type, user_id, role}`
**Errors:** 401 (invalid credentials), 403 (admin/domain roles must use track-specific login)

#### POST `/api/auth/invite`

**Request:** `{username, role?, governed_modules?, email?}`
**Response:** `{user_id, username, role, governed_modules, setup_token, setup_url, email_sent}`
**Errors:** 403 (insufficient role), 409 (username taken)

#### POST `/api/auth/setup-password`

**Request:** `{token, new_password}`
**Response:** `{access_token, token_type, user_id, role}`
**Errors:** 403 (invalid/expired token), 400 (password < 8 chars)

### System-Track Auth

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/admin/auth/login` | none → system | — | System-track login (root, super_admin only) |
| POST | `/api/admin/auth/refresh` | system | root, super_admin | Refresh admin token |
| GET | `/api/admin/auth/me` | system | root, super_admin | Admin profile |

#### POST `/api/admin/auth/login`

**Request:** `{username, password}`
**Response:** `{access_token, token_type, user_id, role}`
**Errors:** 401 (invalid credentials), 403 (non-admin role)

### Domain-Track Auth

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/domain/auth/login` | none → domain | — | Domain-track login (admin only) |
| POST | `/api/domain/auth/refresh` | domain | admin | Refresh domain token |
| GET | `/api/domain/auth/me` | domain | admin | Domain authority profile |

#### POST `/api/domain/auth/login`

**Request:** `{username, password}`
**Response:** `{access_token, token_type, user_id, role}`
**Errors:** 401 (invalid credentials), 403 (non-DA role)

---

## 2. System Log Service

**Package:** `src/lumina/services/system_log/`
**Source routes:** `routes/system_log.py` → `services/system_log/routes.py`, `routes/events.py` → `services/system_log/events_routes.py`

### Log Records

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| GET | `/api/system-log/records` | user | root, operator, half_operator | Query log records |
| GET | `/api/system-log/sessions` | user | root, operator, half_operator | List session IDs with records |
| GET | `/api/system-log/records/{record_id}` | user | root, operator, half_operator | Single record by ID |
| GET | `/api/system-log/warnings` | user | root, operator, half_operator | Warning-level records |
| GET | `/api/system-log/alerts` | user | root, operator, half_operator | Alert-level records |
| GET | `/api/system-log/validate` | any | root, da, operator, half_operator | Hash-chain validation |

#### GET `/api/system-log/records`

**Query params:** `session_id`, `record_type`, `limit`, `offset`
**Response:** `[{record_id, session_id, record_type, timestamp, ...}]`

#### GET `/api/system-log/validate`

**Query params:** `session_id` (optional)
**Response:** `{valid, checked_count, first_mismatch?}`

### SSE Event Stream

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| GET | `/api/events/token` | user | root, da, half_operator, super_admin, operator | Issue short-lived SSE token (5 min) |
| GET | `/api/events/stream` | sse | — | Server-Sent Events stream |

#### GET `/api/events/stream`

**Query params:** `token` (required)
**Response:** `text/event-stream` — JSON frames: `{type, level, category, domain_id, summary, timestamp}`
**RBAC filtering:** root → all events; DA → governed domains; half_operator/super_admin/operator → warning+ only
**Heartbeat:** `:heartbeat` comment every 30s

---

## 3. Ingestion Service

**Package:** `src/lumina/services/ingestion/`
**Source routes:** `routes/ingestion.py` → `services/ingestion/routes.py`, `routes/staging.py` → `services/ingestion/staging_routes.py`

### Document Ingestion

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/ingest/upload` | user | root, da, super_admin | Upload document |
| GET | `/api/ingest` | user | root, da, super_admin, operator | List ingestions |
| GET | `/api/ingest/{ingestion_id}` | user | any | Single ingestion status |
| POST | `/api/ingest/{ingestion_id}/extract` | user | root, da | Run SLM extraction |
| POST | `/api/ingest/{ingestion_id}/review` | user | root, da | Submit review decision |
| POST | `/api/ingest/{ingestion_id}/commit` | user | root, da | Commit to domain pack |

#### POST `/api/ingest/upload`

**Request:** multipart form — `file` (uploaded document), `domain_id`, `description`
**Response:** `{ingestion_id, status: "pending"}`
**Errors:** 400 (missing file), 413 (file too large)

### Staging Workflow

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/staging/create` | user | root, da | Create staged file |
| GET | `/api/staging/pending` | user | root, da | List pending files |
| GET | `/api/staging/{staged_id}` | user | root, da | Staged file details |
| POST | `/api/staging/{staged_id}/approve` | user | root | Approve staged file |
| POST | `/api/staging/{staged_id}/reject` | user | root, da | Reject staged file |

---

## 4. Domain Authority Service

**Package:** `src/lumina/services/domain/`
**Source routes:** `routes/domain.py` → `services/domain/routes.py`, `routes/domain_roles.py` → `services/domain/roles_routes.py`

### Domain Pack Lifecycle

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/domain-pack/commit` | domain / system | root, da | Commit physics hash to System Log |
| GET | `/api/domain-pack/{domain_id}/history` | any | root, da, operator, half_operator | Physics commitment history |
| PATCH | `/api/domain-pack/{domain_id}/physics` | domain / system | root, da | Live-patch domain physics |
| POST | `/api/session/{session_id}/close` | user / system | owner, root, super_admin | Close session |
| POST | `/api/session/{session_id}/handoff` | domain / system | root, da | Handoff session to another authority |
| POST | `/api/session/{session_id}/resume` | domain / system | root, da | Resume handed-off session |

#### PATCH `/api/domain-pack/{domain_id}/physics`

**Request:** `{patch: {...}}` — JSON merge-patch applied to the physics document
**Response:** `{domain_id, new_hash, committed}`
**Errors:** 403 (not governed domain), 404 (domain not found)

### Domain Roles

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| GET | `/api/domain-roles/defaults` | any | any | List default role definitions |
| GET | `/api/domain-roles/{module_id}` | any | any | Get module-specific roles |
| POST | `/api/domain-roles/{module_id}/assign` | domain / system | root, da | Assign domain role |
| DELETE | `/api/domain-roles/{module_id}/{user_id}` | domain / system | root, da | Revoke domain role |

#### POST `/api/domain-roles/{module_id}/assign`

**Request:** `{user_id, role_id}`
**Response:** `{module_id, user_id, role_id, assigned}`
**Errors:** 403 (not governed module), 404 (user/role not found)

---

## 5. Admin & Escalation Service

**Package:** `src/lumina/services/admin/`
**Source routes:** `routes/admin.py`, `routes/ops/*`

### Escalation Lifecycle

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| GET | `/api/escalations` | any | root, super_admin, da, operator, half_operator | List escalations (DA scoped to governed modules) |
| GET | `/api/escalations/{escalation_id}` | any | root, super_admin, operator, half_operator | Single escalation |
| DELETE | `/api/escalations/stale` | system | root | Purge stale escalations |
| POST | `/api/escalations/{escalation_id}/resolve` | any | root, da | Resolve with decision |

#### POST `/api/escalations/{escalation_id}/resolve`

**Request:** `{decision, reasoning, generate_pin?, intervention_notes?, generate_proposal?}`
- `decision`: `"approve"` | `"reject"` | `"defer"`
- `generate_pin`: when `true`, freezes session and returns `unlock_pin`
**Response:** `{record_id, escalation_id, decision, unlock_pin?}`
**Errors:** 404 (not found), 409 (already resolved)

### Audit

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| GET | `/api/audit/log` | any | root, super_admin, operator, half_operator | Scoped audit log entries |

### Manifest Integrity

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| GET | `/api/manifest/check` | any | root, super_admin | Verify artifact SHA-256 hashes |
| POST | `/api/manifest/regen` | system | root | Regenerate manifest hashes |

### HITL Admin Commands

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/admin/command` | system | root, da, super_admin | Parse + stage admin command (SLM) |
| GET | `/api/admin/command/staged` | system | root, da, super_admin | List staged commands |
| POST | `/api/admin/command/{staged_id}/resolve` | system | root, da, super_admin | Execute / reject staged command |

#### Admin Command Operations

Dispatched via `POST /api/admin/command` with a natural-language `instruction`. The SLM parses the instruction into an operation dict, which is staged for HITL review before execution.

| Operation | Module | Description |
|-----------|--------|-------------|
| `update_user_role` | `ops/admin_rbac` | Change a user's system role |
| `deactivate_user` | `ops/admin_rbac` | Deactivate a user account |
| `assign_domain_role` | `ops/admin_rbac` | Assign a domain role within a module |
| `revoke_domain_role` | `ops/admin_rbac` | Revoke a domain role |
| `invite_user` | `ops/admin_invite` | Create invite for a new user |
| `update_domain_physics` | `ops/admin_physics` | Patch domain physics |
| `commit_domain_physics` | `ops/admin_physics` | Commit physics hash |
| `get_domain_physics` | `ops/admin_physics` | Read current physics |
| `module_status` | `ops/admin_physics` | Domain module status |
| `resolve_escalation` | `ops/admin_escalations` | Resolve a pending escalation |
| `list_escalations` | `ops/admin_escalations` | Query escalation records |
| `explain_reasoning` | `ops/admin_escalations` | Explain escalation context |
| `list_ingestions` | `ops/admin_ingestion` | List ingestion records |
| `review_ingestion` | `ops/admin_ingestion` | Review extracted content |
| `approve_interpretation` | `ops/admin_ingestion` | Approve and commit |
| `reject_ingestion` | `ops/admin_ingestion` | Reject ingestion |
| `list_domains` | `ops/admin_queries` | List registered domains |
| `list_commands` | `ops/admin_queries` | List available commands |
| `list_modules` | `ops/admin_queries` | List domain modules |
| `list_domain_rbac_roles` | `ops/admin_queries` | List roles for a module |
| `get_domain_module_manifest` | `ops/admin_queries` | Module manifest data |
| `list_users` | `ops/admin_queries` | List all users |
| `list_daemon_tasks` | `ops/admin_queries` | List daemon task history |
| `view_my_profile` | `ops/admin_profile` | View own profile |
| `update_user_preferences` | `ops/admin_profile` | Update preferences |
| `trigger_daemon_task` | `ops/admin_daemon` | Manually trigger batch run |
| `daemon_status` | `ops/admin_daemon` | Daemon scheduler status |
| `review_proposals` | `ops/admin_daemon` | List pending proposals |

### Session Unlock

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/sessions/{session_id}/unlock` | any | any authenticated | Unfreeze session with OTP PIN |

#### POST `/api/sessions/{session_id}/unlock`

**Request:** `{pin}` — exactly 6 digits
**Response:** `{session_id, unlocked: true}`
**Errors:** 403 (invalid/expired PIN)

---

## 6. Dashboard Service

**Package:** `src/lumina/services/dashboard/`
**Source routes:** `routes/dashboard.py` → `services/dashboard/routes.py`

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| GET | `/api/dashboard/domains` | user | root, da, super_admin | Per-domain summary telemetry |
| GET | `/api/dashboard/telemetry` | user | root, da, super_admin | Aggregate system telemetry |

#### GET `/api/dashboard/domains`

**Response:** `{domain_ids: [...], domains: {<id>: {turn_count, escalation_rate, last_active}}}`

#### GET `/api/dashboard/telemetry`

**Response:** `{active_sessions, pending_escalations, ingestion_queue_depth, last_daemon_run}`

---

## 7. Core Orchestrator

**Source routes:** `routes/chat.py`, `routes/system.py`, `routes/consent.py`, `routes/holodeck.py`, `routes/panels.py`, `routes/vocabulary.py`

### Chat

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/chat` | user (optional) | any | Conversational turn through D.S.A. pipeline |

#### POST `/api/chat`

**Request:** `{session_id?, message, deterministic_response?, turn_data_override?, domain_id?}`
**Response:** `{session_id, response, action, prompt_type, escalated, tool_results, domain_id}`
**Errors:** 400 (empty message), 403 (holodeck role gate), 422 (policy commitment failure), 500 (generic), 503 (system physics error)

**Pipeline:** glossary detection → NLP pre-analysis → SLM physics interpretation → LLM turn interpreter → domain adapter dispatch → weight-routed response

**Frozen session:** PIN-gated unlock; non-PIN messages return `{action: "session_frozen"}`.

### System & Health

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| GET | `/api/health` | none | — | Health check |
| GET | `/api/health/load` | none | — | In-flight request count |
| GET | `/api/domains` | any | any | List registered domains |
| GET | `/api/domain-info` | any | any | Domain metadata + UI manifest |
| POST | `/api/tool/{tool_id}` | user | any | Invoke domain tool adapter |
| GET | `/api/system-log/validate` | any | root, da, operator, half_operator | Hash-chain validation |

### Consent

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/consent/accept` | user | any | Record consent acceptance |

### Holodeck

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/holodeck/simulate` | user | root, da | Run physics sandbox simulation |

#### POST `/api/holodeck/simulate`

**Request:** `{domain_id, scenario, parameters?}`
**Response:** `{simulation_id, results, warnings, domain_id}`
**Errors:** 403 (insufficient role), 404 (domain not found)

### Panels

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| GET | `/api/panels/{panel_id}` | user | any | Resolve panel data from role layout |
| PATCH | `/api/panels/{panel_id}` | user | any | Update panel (self_preferences only) |

#### GET `/api/panels/{panel_id}`

**Response:** Panel-specific data resolved from 11 data-source resolvers based on role layout configuration.
**Errors:** 401 (unauthenticated), 404 (panel not found in layout)

#### PATCH `/api/panels/{panel_id}`

**Request:** `{updates: {...}}` — only `self_preferences` source is writable
**Response:** `{panel_id, updated: true}`
**Errors:** 401 (unauthenticated), 403 (non-writable source), 404 (panel not found)

### Daemon Batch Operations

Batch processing operations (trigger, status, report, proposals, resolve) are dispatched
through `POST /api/admin/command` with the appropriate `operation` field:
`trigger_daemon_task`, `daemon_status`, `daemon_report`, `review_proposals`, `resolve_proposal`.
See Section 1 (Admin) for the admin command endpoint specification.

### Vocabulary

| Method | Path | Track | Roles | Description |
|--------|------|-------|-------|-------------|
| POST | `/api/user/{user_id}/vocabulary-metric` | user | any | Submit vocabulary metric |
| GET | `/api/dashboard/education/vocabulary-growth` | user | root, da, operator, half_operator | Vocabulary growth dashboard |

#### POST `/api/user/{user_id}/vocabulary-metric`

**Request:** `{term, domain_id?, mastery_level?, context?}`
**Response:** `{recorded: true}`
**Errors:** 401 (unauthenticated), 403 (user_id mismatch with token)

---

## Error Code Summary

| Code | Meaning | Common Triggers |
|------|---------|-----------------|
| 400 | Bad Request | Missing required fields, empty message, invalid format |
| 401 | Unauthorized | Missing/expired/invalid token, wrong JWT track |
| 403 | Forbidden | Insufficient role, scope mismatch, wrong track |
| 404 | Not Found | Resource ID not found |
| 409 | Conflict | Duplicate (username, ingestion), already resolved |
| 410 | Gone | Expired staged command |
| 413 | Payload Too Large | Upload exceeds size limit |
| 422 | Unprocessable Entity | Policy commitment gate failure |
| 429 | Too Many Requests | Max contexts per session exceeded |
| 500 | Internal Server Error | Unhandled exception |
| 503 | Service Unavailable | System physics error, SLM unavailable |

---

## SEE ALSO

- [lumina-api-server(2)](lumina-api-server.md) — server synopsis, environment variables, pipeline details
- [parallel-authority-tracks(7)](../7-concepts/parallel-authority-tracks.md) — three-track JWT model
- [microservice-boundaries(7)](../7-concepts/microservice-boundaries.md) — service decomposition and ownership
- [zero-trust-architecture(7)](../7-concepts/zero-trust-architecture.md) — security enforcement layers
- [air-gapped-admin-architecture(8)](../8-admin/air-gapped-admin-architecture.md) — admin token isolation
- [auth(3)](../3-functions/auth.md) — JWT implementation details
