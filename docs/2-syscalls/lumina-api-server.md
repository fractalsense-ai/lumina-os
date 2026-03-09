# lumina-api-server(2)

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
| `LUMINA_LLM_PROVIDER` | `openai` | LLM backend: `openai` or `anthropic` |
| `LUMINA_OPENAI_MODEL` | `gpt-4o` | OpenAI model name |
| `LUMINA_ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Anthropic model name |
| `LUMINA_RUNTIME_CONFIG_PATH` | — | Override path to runtime-config.yaml |
| `LUMINA_PERSISTENCE_BACKEND` | `filesystem` | `filesystem` or `sqlite` |
| `LUMINA_DB_URL` | `sqlite+aiosqlite:///lumina.db` | SQLAlchemy database URL |
| `LUMINA_PORT` | `8000` | HTTP listen port |
| `LUMINA_ENFORCE_POLICY_COMMITMENT` | `true` | Require CTL-committed domain-physics hash |
| `LUMINA_JWT_SECRET` | — | **Required.** HMAC signing key for JWT tokens |
| `LUMINA_JWT_TTL_MINUTES` | `60` | Token time-to-live |
| `LUMINA_JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `LUMINA_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed CORS origins |
| `LUMINA_BOOTSTRAP_MODE` | `true` | First registered user auto-promoted to root |

---

## ENDPOINTS

### POST /api/chat

Process a conversational turn through the D.S.A. pipeline.

**Request:** `ChatRequest` — `session_id`, `message`, `deterministic_response`, `turn_data_override`

**Response:** `ChatResponse` — `session_id`, `response`, `action`, `prompt_type`, `escalated`, `tool_results`

**Auth:** Optional Bearer token. When provided, module execute permission is checked.

---

### GET /api/health

Returns `{"status": "ok", "provider": "<llm_provider>"}`.

---

### GET /api/domain-info

Returns domain ID, version, and UI manifest for front-end theming.

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

[dsa-framework](../../specs/dsa-framework-v1.md), [rbac-spec](../../specs/rbac-spec-v1.md), [auth(3)](../3-functions/auth.md)
