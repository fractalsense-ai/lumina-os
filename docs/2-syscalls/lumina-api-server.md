# lumina-api-server(2)

**Version:** 1.2.0  
**Status:** Active  
**Last updated:** 2026-03-19  

---

## NAME

`lumina-api-server` — Project Lumina Integration Server

## SYNOPSIS

```bash
# Module invocation
python -m lumina.api.server

# Installed entrypoint (after pip install)
lumina-api
```

## DESCRIPTION

Generic runtime host for D.S.A. orchestration with built-in JWT authentication. Loads runtime behavior from domain-owned config, keeps the core server free of domain-specific logic, and routes each turn through orchestrator prompt contracts and CTL.

`src/lumina/api/server.py` is a **thin app factory** (~200 lines). All business logic is distributed across dedicated sub-modules:

| Module | Responsibility |
|--------|---------------|
| `config.py` | Env-var singletons: `DOMAIN_REGISTRY`, `PERSISTENCE`, feature flags |
| `session.py` | `SessionContainer`, `DomainContext`, `get_or_create_session` |
| `models.py` | Pydantic request/response models |
| `middleware.py` | JWT bearer scheme, `require_auth`, `require_role` |
| `llm.py` | `call_llm` — provider dispatch (`openai`, `anthropic`, `local`, `google`, `azure`, `mistral`) |
| `processing.py` | `process_message` — six-stage per-turn pipeline; frozen-session gate |
| `runtime_helpers.py` | `render_contract_response`, `invoke_runtime_tool` |
| `core/session_unlock.py` | In-memory OTP PIN store for session unlock |
| `utils/text.py` | LaTeX regex helpers, `strip_latex_delimiters` |
| `utils/glossary.py` | `detect_glossary_query`, per-domain definition cache |
| `utils/coercion.py` | `normalize_turn_data`, field-type coercers |
| `utils/templates.py` | Template rendering for tool-call policy strings |
| `routes/chat.py` | `POST /api/chat` |
| `routes/auth.py` | Auth and user-management endpoints |
| `routes/admin.py` | Escalation, audit, manifest, and HITL admin-command endpoints |
| `routes/ctl.py` | CTL record-browsing endpoints |
| `routes/domain.py` | Domain-pack lifecycle and session-close endpoints |
| `routes/ingestion.py` | Document ingestion pipeline endpoints |
| `routes/system.py` | Health, domain listing, tool adapter, CTL validate |
| `routes/dashboard.py` | Governance dashboard data endpoints |
| `routes/nightcycle.py` | Night-cycle trigger, status, and proposal endpoints |

## ENVIRONMENT

| Variable | Default | Description |
|----------|---------|-------------|
| `LUMINA_LLM_PROVIDER` | `openai` | LLM backend: `openai`, `anthropic`, `local`, `google`, `azure`, or `mistral` |
| `LUMINA_OPENAI_MODEL` | `gpt-4o` | OpenAI model name |
| `LUMINA_ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Anthropic model name |
| `LUMINA_LLM_MODEL` | `llama3` | Model name for the `local` provider |
| `LUMINA_LLM_ENDPOINT` | `http://localhost:11434` | Base URL for the `local` provider (Ollama/vLLM/LM Studio/TGI/OpenRouter) |
| `LUMINA_LLM_TIMEOUT` | `120` | HTTP timeout in seconds for the `local` provider |
| `LUMINA_GOOGLE_MODEL` | `gemini-2.0-flash` | Gemini model name for the `google` provider |
| `LUMINA_AZURE_OPENAI_ENDPOINT` | — | Azure OpenAI resource endpoint (required for `azure` provider) |
| `LUMINA_AZURE_OPENAI_DEPLOYMENT` | — | Azure OpenAI deployment name (required for `azure` provider) |
| `LUMINA_AZURE_OPENAI_API_VERSION` | `2024-08-01-preview` | Azure OpenAI API version |
| `LUMINA_MISTRAL_MODEL` | `mistral-large-latest` | Mistral model name for the `mistral` provider |
| `OPENAI_API_KEY` | — | Required when `LUMINA_LLM_PROVIDER=openai` and live mode is used |
| `ANTHROPIC_API_KEY` | — | Required when `LUMINA_LLM_PROVIDER=anthropic` and live mode is used |
| `GOOGLE_API_KEY` | — | Required when `LUMINA_LLM_PROVIDER=google` |
| `AZURE_OPENAI_API_KEY` | — | Required when `LUMINA_LLM_PROVIDER=azure` |
| `MISTRAL_API_KEY` | — | Required when `LUMINA_LLM_PROVIDER=mistral` |
| `LUMINA_RUNTIME_CONFIG_PATH` | — | Override path to runtime-config.yaml (single-domain mode) |
| `LUMINA_DOMAIN_REGISTRY_PATH` | — | Path to domain-registry.yaml (multi-domain mode) |
| `LUMINA_PERSISTENCE_BACKEND` | `filesystem` | `filesystem` or `sqlite` |
| `LUMINA_DB_URL` | `sqlite+aiosqlite:///lumina.db` | SQLAlchemy database URL |
| `LUMINA_PORT` | `8000` | HTTP listen port |
| `LUMINA_ENFORCE_POLICY_COMMITMENT` | `true` | Require CTL-committed domain-physics hash |
| `LUMINA_JWT_SECRET` | — | **Required.** HMAC signing key for JWT tokens |
| `LUMINA_JWT_TTL_MINUTES` | `60` | Token time-to-live |
| `LUMINA_JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `LUMINA_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed CORS origins |
| `LUMINA_BOOTSTRAP_MODE` | `true` | First registered user auto-promoted to root |
| `LUMINA_SLM_PROVIDER` | `local` | SLM backend: `local` (Ollama/llama.cpp), `openai`, or `anthropic` |
| `LUMINA_SLM_MODEL` | `phi-3` | Model name forwarded to the SLM backend |
| `LUMINA_SLM_ENDPOINT` | `http://localhost:11434` | Base URL for the local provider; ignored for cloud providers |
| `LUMINA_SESSION_IDLE_TIMEOUT_MINUTES` | `30` | Reap sessions idle longer than this value; `0` disables idle reaping |
| `LUMINA_STAGED_CMD_TTL_SECONDS` | `300` | TTL for HITL-staged admin commands before they expire |
| `LUMINA_MAX_CONTEXTS_PER_SESSION` | `10` | Maximum number of per-domain contexts a single session may hold |
| `LUMINA_UNLOCK_PIN_TTL_SECONDS` | `900` | TTL in seconds for in-memory session-unlock OTP PINs |

Notes:

- Deterministic mode (`deterministic_response=true`) does not require provider API keys.
- Live mode requires the provider key for the selected backend.
- Production secret handling guidance: [secrets-and-runtime-config](../8-admin/secrets-and-runtime-config.md)

---

## ENDPOINTS

### POST /api/chat

Process a conversational turn through the D.S.A. pipeline.

**Request:** `ChatRequest` — `session_id`, `message`, `deterministic_response`, `turn_data_override`, `domain_id`

**Response:** `ChatResponse` — `session_id`, `response`, `action`, `prompt_type`, `escalated`, `tool_results`, `domain_id`

**Auth:** Optional Bearer token. When provided, module execute permission is checked against the resolved domain.

**Pipeline:** Each turn passes through six stages before the orchestrator receives the evidence dict:

1. **Glossary detection** — domain-defined vocabulary terms are matched in the raw message; a match short-circuits D.S.A. and returns an inline definition response directly. When the SLM is available the Librarian role renders the definition; otherwise the `"{term}: {definition}"` deterministic template is used.
2. **NLP pre-analysis** — `nlp_preprocess()` runs deterministic extraction (<1 ms) and appends `_nlp_anchors` to the LLM context hint; provides answer-match confidence, frustration markers, hint requests, and off-task ratio without blocking the LLM.
3. **SLM physics interpretation** — the SLM Physics Interpreter role compresses the session's domain context into a token-efficient summary that is prepended to the LLM prompt; skipped transparently when the SLM is unavailable.
4. **LLM turn interpreter** — receives the full message plus NLP anchor hints and SLM-compressed physics context; produces structured evidence fields.
5. **Domain adapter dispatch** — education domain algebra-parser override applies post-LLM for `solution_value`, `step_count`, and `equivalence_preserved`; agriculture and other adapters receive the same interface with no NLP kwargs injected.
6. **Weight-routed response dispatch** — `classify_task_weight()` assigns LOW or HIGH weight to the resolved action; LOW-weight prompt types (definitions, confirmations) are served by the SLM, HIGH-weight types (explanations, scaffolding) go to the primary LLM.

**Notes:** `domain_id` selects which domain context to use. When omitted, the default domain is used. Each session maintains an isolated `DomainContext` per domain; a single session may span multiple domains up to `LUMINA_MAX_CONTEXTS_PER_SESSION`.

**Frozen-session behaviour:** When a `SessionContainer` has `frozen=True` (set by a teacher-initiated escalation resolve with `generate_pin=true`), the chat pipeline is short-circuited before the six stages run:

- Any message that is **not** a valid 6-digit PIN returns `{"action": "session_frozen", "escalated": true, "response": "This session is temporarily locked pending teacher review."}` with HTTP 200.
- A message that is exactly 6 digits and **matches the stored OTP** for this session unfreezes the session and returns `{"action": "session_unlocked", "escalated": false, "response": "Session unlocked. You may continue."}` with HTTP 200. The PIN is consumed on first use.
- A message that is 6 digits but does **not** match (wrong PIN, expired PIN, or no PIN stored) is treated as a normal frozen message and returns `session_frozen`.

---

### GET /api/health

Returns `{"status": "ok", "provider": "<llm_provider>"}`.

---

### GET /api/domains

List available domains in a multi-domain deployment.

**Response:** Array of `{domain_id, label, description, is_default}`.

---

### GET /api/domain-info

Returns domain ID, version, and UI manifest for front-end theming.

**Query parameters:** `domain_id` (optional — uses default when omitted).

---

### POST /api/tool/{tool_id}

Invoke a domain tool adapter.

**Auth:** Optional Bearer token with execute permission check.

---

### GET /api/ctl/validate

Validate CTL hash-chain integrity. Optional `session_id` query parameter.

**Auth:** Optional Bearer token. When provided, requires role: `root`, `domain_authority`, `qa`, or `auditor`.

---

### GET /api/ctl/records

List CTL commitment records. Query parameters: `session_id`, `record_type`, `limit`, `offset`.

**Auth:** Bearer token required. Roles: `root`, `it_support`, `qa`, `auditor`.

---

### GET /api/ctl/sessions

List session IDs that have CTL records.

**Auth:** Bearer token required. Roles: `root`, `it_support`, `qa`, `auditor`.

---

### GET /api/ctl/records/{record_id}

Retrieve a single CTL commitment record by ID.

**Auth:** Bearer token required. Roles: `root`, `it_support`, `qa`, `auditor`.

---

### GET /api/escalations

List escalation records. Query parameters: `status`, `domain_id`, `limit`, `offset`.

**Auth:** Bearer token required. Roles: `root`, `it_support`, `qa`, `auditor`, `domain_authority` (scoped to governed modules).

---

### POST /api/escalations/{escalation_id}/resolve

Resolve an open escalation with a decision.

**Request:** `EscalationResolveRequest`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `decision` | `string` | required | `"approve"`, `"reject"`, or `"defer"` |
| `reasoning` | `string` | required | Free-text rationale recorded in the CTL |
| `generate_pin` | `bool` | `false` | When `true`, generates a 6-digit OTP, freezes the session, and returns `unlock_pin` in the response |
| `intervention_notes` | `string \| null` | `null` | Free-text intervention notes appended to the student's `intervention_history` in their profile |
| `generate_proposal` | `bool` | `false` | Marks the intervention notes entry for night-cycle proposal generation |

**Response:** `{record_id, escalation_id, decision}` plus `unlock_pin` (6-digit string) when `generate_pin=true`.

**Auth:** Bearer token required. Roles: `root`, `domain_authority`.

**Notes:** Setting `generate_pin=true` both generates the PIN (stored in memory, TTL from `LUMINA_UNLOCK_PIN_TTL_SECONDS`) and atomically sets `SessionContainer.frozen=True` for the session. The teacher delivers the PIN to the student out-of-band. See [escalation-pin-unlock](../8-admin/escalation-pin-unlock.md) for the full workflow.

---

### POST /api/sessions/{session_id}/unlock

Unfreeze a frozen session by submitting the OTP PIN issued during escalation resolve.

**Request:** `SessionUnlockRequest` — `pin` (string, exactly 6 digits)

**Response:** `{session_id, unlocked: true}`

**Auth:** Bearer token required. Any authenticated user may call this endpoint.

**Errors:** `403` when the PIN is invalid, expired, or no PIN is pending for this session.

**Notes:** For in-chat PIN entry (student submits the 6-digit PIN as a chat message) see the frozen-session behaviour note on `POST /api/chat`. Both paths consume the PIN on first use.

---

### GET /api/audit/log

Return audit log entries. Query parameters: `actor_id`, `record_type`, `domain_id`, `limit`, `offset`.

**Auth:** Bearer token required. Roles: `root`, `it_support`, `qa`, `auditor`.

---

### GET /api/manifest/check

Verify that all artifacts listed in `docs/MANIFEST.yaml` have matching sha256 digests on disk.

**Response:** `ManifestCheckResponse` — `ok`, `mismatches` (list of `{path, expected, actual}`).

**Auth:** Bearer token required. Roles: `root`, `it_support`.

---

### POST /api/manifest/regen

Recompute sha256 digests for all artifacts in `docs/MANIFEST.yaml` and write them back to the file.

**Response:** `ManifestRegenResponse` — `updated_count`, `manifest_path`.

**Auth:** Bearer token required. Role: `root`.

---

### POST /api/admin/command

Parse and stage a natural-language admin instruction via the SLM. Returns a `staged_id` that must be resolved before the command executes (**HITL gate**).

**Request:** `AdminCommandRequest` — `instruction`

**Response:** `staged_id`, `staged_command` (parsed operation dict), `original_instruction`, `expires_at`, `ctl_stage_record_id`

**Auth:** Bearer token required. Roles: `root`, `domain_authority`, `it_support`.

**Notes:** Staged commands expire after `LUMINA_STAGED_CMD_TTL_SECONDS` seconds. Each staging is recorded in the admin CTL ledger before the response is returned.

---

### POST /api/admin/command/{staged_id}/resolve

Accept, reject, or modify a previously staged admin command.

**Request:** `CommandResolveRequest` — `action` (`accept` | `reject` | `modify`), `override_params` (optional)

**Auth:** Bearer token required. Roles: `root`, `domain_authority`, `it_support`. Non-root users may only resolve their own staged commands.

---

### POST /api/auth/register

Register a new user account.

**Request:** `RegisterRequest` — `username`, `password`, `role` (default: `user`), `governed_modules`

**Response:** `TokenResponse` — `access_token`, `token_type`, `user_id`, `role`

**Notes:** In bootstrap mode, the first registered user is automatically assigned the `root` role. Password must be at least 8 characters.

---

### POST /api/auth/login

Authenticate with username/password and receive a JWT.

**Request:** `LoginRequest` — `username`, `password`

**Response:** `TokenResponse`

---

### GET /api/auth/guest-token

Issue a short-lived (30 min) guest JWT. No credentials required. Guest tokens carry the `guest` role.

**Response:** `TokenResponse`

---

### POST /api/auth/refresh

Issue a fresh token for the currently authenticated user.

**Auth:** Bearer token required.

---

### GET /api/auth/me

Return the profile of the currently authenticated user.

**Auth:** Bearer token required.

---

### GET /api/auth/users

List all registered users (password hashes excluded).

**Auth:** Bearer token required. Roles: `root`, `it_support`.

---

### PATCH /api/auth/users/{user_id}

Update a user's role or governed modules.

**Request:** `UserUpdateRequest` — `role` (optional), `governed_modules` (optional)

**Auth:** Bearer token required. Role: `root`.

---

### DELETE /api/auth/users/{user_id}

Delete a user account.

**Auth:** Bearer token required. Role: `root`.

---

### POST /api/auth/revoke

Add the caller's current JWT to the server-side revocation list.

**Auth:** Bearer token required.

---

### POST /api/auth/password-reset

Reset a user's password. Root may reset any user; non-root may only reset their own.

**Request:** `PasswordResetRequest` — `user_id`, `new_password`

**Auth:** Bearer token required.

---

### POST /api/domain-pack/commit

Commit a domain-physics hash to the CTL, establishing the authoritative version for a domain.

**Auth:** Bearer token required. Roles: `root`, `domain_authority` (governed domain only).

---

### GET /api/domain-pack/{domain_id}/history

Return the CTL commitment history for a domain's physics hash.

**Auth:** Bearer token required. Roles: `root`, `domain_authority`, `qa`, `auditor`.

---

### PATCH /api/domain-pack/{domain_id}/physics

Apply a live patch to a domain's physics document and auto-commit a new CTL record.

**Auth:** Bearer token required. Roles: `root`, `domain_authority` (governed domain only).

---

### POST /api/session/{session_id}/close

Explicitly close a session, flushing its CTL ledger and releasing memory.

**Auth:** Bearer token required. Users may close their own sessions; `root` and `it_support` may close any session.

---

### POST /api/ingest/upload

Upload a document artifact and open an ingestion record.

**Response:** `ingestion_id`, `status: pending`

**Auth:** Bearer token required. Roles: `root`, `domain_authority`, `it_support`.

---

### GET /api/ingest/{ingestion_id}

Return the status and metadata for an ingestion record.

**Auth:** Bearer token required.

---

### POST /api/ingest/{ingestion_id}/extract

Trigger SLM-based entity and glossary extraction from the uploaded document.

**Auth:** Bearer token required. Roles: `root`, `domain_authority`.

---

### POST /api/ingest/{ingestion_id}/review

Submit a human review decision on extracted content before commit.

**Request:** `IngestionReviewRequest` — `approved_entries`, `rejected_entries`, `notes`

**Auth:** Bearer token required. Roles: `root`, `domain_authority`.

---

### POST /api/ingest/{ingestion_id}/commit

Finalize an ingestion: write approved entries to the domain physics and record the CTL commitment.

**Auth:** Bearer token required. Roles: `root`, `domain_authority`.

---

### GET /api/ingest

List ingestion records. Query parameters: `domain_id`, `status`, `limit`, `offset`.

**Auth:** Bearer token required. Roles: `root`, `domain_authority`, `it_support`, `qa`.

---

### GET /api/dashboard/domains

Return per-domain summary telemetry (turn count, escalation rate, last active timestamp).

**Auth:** Bearer token required. Roles: `root`, `domain_authority`, `it_support`.

---

### GET /api/dashboard/telemetry

Return aggregate system telemetry (active sessions, pending escalations, ingestion queue depth, last night-cycle run).

**Auth:** Bearer token required. Roles: `root`, `domain_authority`, `it_support`.

---

### POST /api/nightcycle/trigger

Trigger an immediate night-cycle batch run for one or all domains.

**Request:** `NightcycleTriggerRequest` — `domain_id` (optional; omit for all domains)

**Auth:** Bearer token required. Role: `root`.

---

### GET /api/nightcycle/status

Return the status of the most recent night-cycle run.

**Auth:** Bearer token required. Roles: `root`, `domain_authority`, `it_support`.

---

### GET /api/nightcycle/report/{run_id}

Return the full report for a completed night-cycle run.

**Auth:** Bearer token required. Roles: `root`, `domain_authority`, `it_support`, `qa`.

---

### GET /api/nightcycle/proposals

List pending night-cycle proposals (glossary additions/prunings, consistency fixes) awaiting domain-authority review.

**Auth:** Bearer token required. Roles: `root`, `domain_authority`.

---

### POST /api/nightcycle/proposals/{proposal_id}/resolve

Accept or reject a night-cycle proposal.

**Request:** `ProposalResolveRequest` — `decision` (`accept` | `reject`), `notes`

**Auth:** Bearer token required. Roles: `root`, `domain_authority`.

---

## SEE ALSO

[dsa-framework](../../specs/dsa-framework-v1.md) (D.S.A. structural schema underlying PPA), [rbac-spec](../../specs/rbac-spec-v1.md), [auth(3)](../3-functions/auth.md), [api-server-architecture](../7-concepts/api-server-architecture.md)
