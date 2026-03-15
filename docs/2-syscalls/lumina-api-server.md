# lumina-api-server(2)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`lumina-api-server.py` — Project Lumina Integration Server

## SYNOPSIS

```bash
python reference-implementations/lumina-api-server.py
```

## DESCRIPTION

Generic runtime host for D.S.A. orchestration with built-in JWT authentication. Loads runtime behavior from domain-owned config, keeps the core server free of domain-specific logic, and routes each turn through orchestrator prompt contracts and CTL.

## ENVIRONMENT

| Variable | Default | Description |
|----------|---------|-------------|
| `LUMINA_LLM_PROVIDER` | `openai` | LLM backend: `openai` or `anthropic` (used for live mode) |
| `LUMINA_OPENAI_MODEL` | `gpt-4o` | OpenAI model name |
| `LUMINA_ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Anthropic model name |
| `OPENAI_API_KEY` | — | Required when `LUMINA_LLM_PROVIDER=openai` and live mode is used |
| `ANTHROPIC_API_KEY` | — | Required when `LUMINA_LLM_PROVIDER=anthropic` and live mode is used |
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

**Notes:** `domain_id` selects which domain context to use. When omitted, the default domain is used. Sessions are immutably bound to their initial domain.

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

**Auth:** Bearer token required. Only `root` and `it_support` roles.

## SEE ALSO

[dsa-framework](../../specs/dsa-framework-v1.md) (D.S.A. structural schema underlying PPA), [rbac-spec](../../specs/rbac-spec-v1.md), [auth(3)](../3-functions/auth.md)
