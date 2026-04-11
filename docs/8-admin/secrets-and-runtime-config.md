---
version: 1.2.0
last_updated: 2026-03-21
---

# secrets-and-runtime-config

**Version:** 1.2.0
**Status:** Active
**Last updated:** 2026-03-21

---

Production-safe runtime configuration for Project Lumina.

## Goal

Use environment injection for secrets in staging/production, never committed secret files.

## Runtime modes

- Deterministic mode: no provider API key required (`deterministic_response=true`).
- Live LLM mode: provider API key is required for cloud providers (see below).
- Live mode guardrail: runtime rejects live provider calls when the selected provider key is missing.
- Local/self-hosted mode (`LUMINA_LLM_PROVIDER=local`): no API key required; connects to Ollama, vLLM, LM Studio, TGI, OpenRouter, or any OpenAI-compatible cluster endpoint. Set `LUMINA_LLM_ENDPOINT`, `LUMINA_LLM_MODEL`, and optionally `LUMINA_LLM_TIMEOUT`. See [installation-and-packaging — Primary LLM setup](../1-commands/installation-and-packaging.md#primary-llm-setup) for step-by-step Ollama setup.

## Required production variables

- `LUMINA_RUNTIME_CONFIG_PATH` (single-domain) **or** `LUMINA_DOMAIN_REGISTRY_PATH` (multi-domain)
- `LUMINA_LOG_DIR` — System Log root directory; auto-created at startup

### JWT secrets

Lumina uses a **three-track JWT architecture** separating admin, domain, and user tokens:

| Variable | Required when | Description |
|----------|---------------|-------------|
| `LUMINA_JWT_SECRET` | Always | Legacy shared secret; fallback when track-specific secrets are absent |
| `LUMINA_ADMIN_JWT_SECRET` | Production (admin track) | Signs tokens for `root`, `it_support`; `iss: lumina-admin` |
| `LUMINA_DOMAIN_JWT_SECRET` | Production (domain track) | Signs tokens for `domain_authority`; `iss: lumina-domain` |
| `LUMINA_USER_JWT_SECRET` | Production (user track) | Signs tokens for `user`, `qa`, `auditor`, `guest`; `iss: lumina-user` |

#### JWT air-gap setup

When all three track-specific secrets are set, the tracks are cryptographically
isolated:

- Admin roles (`root`, `it_support`) authenticate via `POST /api/admin/auth/login` —
  tokens carry `iss: lumina-admin` and are validated against `LUMINA_ADMIN_JWT_SECRET`.
- Domain authorities authenticate via `POST /api/domain/auth/login` — tokens carry
  `iss: lumina-domain` and are validated against `LUMINA_DOMAIN_JWT_SECRET`.
- User roles authenticate via `POST /api/auth/login` — tokens carry `iss: lumina-user`
  and are validated against `LUMINA_USER_JWT_SECRET`.

A compromised secret on one track cannot be used to forge tokens for another track.
When only `LUMINA_JWT_SECRET` is set all tokens share one secret (development
mode only — not recommended for production).

See [air-gapped-admin-architecture(8)](air-gapped-admin-architecture.md) for
the full three-tier model, token lifecycle, and rotation guidance.

```bash
# Generate each secret independently
python -c "import secrets; print(secrets.token_hex(32))"
```

Conditionally required:

- `OPENAI_API_KEY` when `LUMINA_LLM_PROVIDER=openai`
- `ANTHROPIC_API_KEY` when `LUMINA_LLM_PROVIDER=anthropic`
- `GOOGLE_API_KEY` when `LUMINA_LLM_PROVIDER=google`
- `AZURE_OPENAI_API_KEY` + `LUMINA_AZURE_OPENAI_ENDPOINT` + `LUMINA_AZURE_OPENAI_DEPLOYMENT` when `LUMINA_LLM_PROVIDER=azure`
- `MISTRAL_API_KEY` when `LUMINA_LLM_PROVIDER=mistral`

## Recommended production variables

- `LUMINA_LLM_PROVIDER`
- `LUMINA_OPENAI_MODEL`, `LUMINA_ANTHROPIC_MODEL`, `LUMINA_LLM_MODEL`, `LUMINA_GOOGLE_MODEL`, or `LUMINA_MISTRAL_MODEL` (depending on selected provider)
- `LUMINA_ENFORCE_POLICY_COMMITMENT=true`
- `LUMINA_BOOTSTRAP_MODE=false`
- `LUMINA_CORS_ORIGINS`
- `LUMINA_PORT`
- `LUMINA_PASSWORD_HASH_ALGORITHM` (default: `argon2id`)

### System Log directory

| Variable | Description |
|----------|-------------|
| `LUMINA_LOG_DIR` | Primary System Log root; auto-created at startup. **Set this in production.** |
| `LUMINA_CTL_DIR` | Backward-compatible fallback (deprecated — prefer `LUMINA_LOG_DIR`; still accepted) |

## Local development setup

1. Copy template:

```bash
cp .env.example .env
```

2. Fill `.env` values with local secrets and runtime settings.

3. Export variables in your shell or deployment launcher.

PowerShell example:

```powershell
$env:LUMINA_RUNTIME_CONFIG_PATH = "domain-packs/education/runtime-config.yaml"
$env:LUMINA_LLM_PROVIDER = "openai"
$env:OPENAI_API_KEY = "<your-local-key>"
$env:LUMINA_JWT_SECRET = "<32-byte-or-longer-random-secret>"
```

POSIX example:

```bash
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/education/runtime-config.yaml"
export LUMINA_LLM_PROVIDER="openai"
export OPENAI_API_KEY="<your-local-key>"
export LUMINA_JWT_SECRET="<32-byte-or-longer-random-secret>"
```

## Generate a JWT secret

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Password hashing

The default algorithm is Argon2id, which requires the `argon2-cffi` package.
When the required library is not installed, the system falls back gracefully:
argon2id → bcrypt → sha256.

```bash
# Install both password hashing backends
pip install project-lumina[passwords]

# Or install individually
pip install argon2-cffi   # Argon2id — recommended default
pip install bcrypt         # bcrypt — battle-tested alternative
```

Configure via environment variable:

```bash
export LUMINA_PASSWORD_HASH_ALGORITHM="argon2id"   # default
# export LUMINA_PASSWORD_HASH_ALGORITHM="bcrypt"
# export LUMINA_PASSWORD_HASH_ALGORITHM="sha256"
```

SHA-256 is always available as a zero-dependency fallback but is not
recommended for production deployments.

## Production deployment guidance

- Inject secrets through your platform secret manager (for example: container orchestrator secrets, CI/CD secret store, cloud app settings).
- Do not store provider keys or JWT secrets in committed files.
- Rotate `LUMINA_JWT_SECRET` and provider keys periodically and after incidents.
- Keep `LUMINA_BOOTSTRAP_MODE=false` after initial provisioning.

## Multi-domain deployment

A single Lumina instance can serve multiple departments or domains
(for example math, science, PE, literature) by using a **domain registry**
instead of a single `LUMINA_RUNTIME_CONFIG_PATH`.

1. Create a `domain-registry.yaml` mapping each `domain_id` to its
   `runtime-config.yaml`:

   ```yaml
   default_domain: education
   domains:
     education:
       runtime_config_path: domain-packs/education/runtime-config.yaml
       label: Education — Algebra Level 1
     agriculture:
       runtime_config_path: domain-packs/agriculture/runtime-config.yaml
       label: Agriculture — Operations
   ```

2. Set the environment variable:

   ```bash
   export LUMINA_DOMAIN_REGISTRY_PATH="domain-registry.yaml"
   ```

3. Remove or unset `LUMINA_RUNTIME_CONFIG_PATH` (registry takes precedence
   when both are set, but only one should be active).

4. Clients select a domain per chat request via the `domain_id` field:

   ```json
   {"message": "solve 2x + 3 = 11", "domain_id": "education"}
   ```

5. Sessions are **immutably bound** to the domain chosen on their first turn.
   Attempting to switch `domain_id` mid-session returns an error.

6. Use `GET /api/domains` to list available domains and
   `GET /api/domain-info?domain_id=education` for per-domain UI manifests.

Schema: `standards/domain-registry-schema-v1.json`

## SLM configuration

The SLM (Small Language Model) layer handles low-weight tasks — glossary rendering, physics context compression, and admin command translation — without consuming primary LLM quota. It is entirely optional; the server falls back to deterministic templates when the SLM is unavailable.

| Variable | Default | Description |
|----------|---------|-------------|
| `LUMINA_SLM_PROVIDER` | `local` | Backend: `local` (Ollama/llama.cpp), `openai`, or `anthropic` |
| `LUMINA_SLM_MODEL` | `gemma3:4b` | Model name forwarded to the provider |
| `LUMINA_SLM_ENDPOINT` | `http://localhost:11434` | Base URL for the local provider; ignored for cloud providers |

Cloud SLM providers (`openai`, `anthropic`) reuse the same `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` secrets already required for the primary LLM — no additional key is needed.

Full setup instructions including Ollama install steps and end-to-end verification: [installation-and-packaging — SLM setup](../1-commands/installation-and-packaging.md#slm-small-language-model-setup)

## Related docs

- [installation-and-packaging(1)](../1-commands/installation-and-packaging.md)
- [lumina-api-server(2)](../2-syscalls/lumina-api-server.md)
- [air-gapped-admin-architecture(8)](air-gapped-admin-architecture.md)
- [rbac-administration](rbac-administration.md)
