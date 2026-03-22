---
version: 1.2.0
last_updated: 2026-03-21
---

# installation-and-packaging(1)

**Version:** 1.2.0  
**Status:** Active  
**Last updated:** 2026-03-21  

---

## NAME

installation-and-packaging — install, configure, and run Project Lumina

## SYNOPSIS

```
pip install -e .[nlp,providers,sqlite]
lumina-api
```

## DESCRIPTION

Installation and packaging workflows for Project Lumina. Covers dependency
installation, the editable package install, primary LLM and SLM provider
setup, JWT secret configuration, CLI entrypoints, the React frontend, and
PowerShell utility scripts.

Before running live LLM mode, configure runtime secrets and environment
settings: [secrets-and-runtime-config](../8-admin/secrets-and-runtime-config.md).

## Requirements files workflow (pip)

Runtime dependencies:

```bash
pip install -r requirements.txt
```

Runtime + development dependencies:

```bash
pip install -r requirements-dev.txt
```

## One-liner developer setup (uv)

```bash
uv venv && uv pip install -r requirements-dev.txt
```

## Editable install (pyproject)

Use editable install when you want command entrypoints and local package iteration.

First, create and activate a venv. On Windows, use the `py` launcher to pin a specific Python version — this is required when installing the `nlp` extra, since spaCy is not yet compatible with Python 3.14+:

```powershell
# Windows (PowerShell)
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
python3.13 -m venv .venv
source .venv/bin/activate
```

Once the venv is active, use plain `pip` — not `python -m pip`:

```bash
# Minimal (FastAPI + uvicorn only)
pip install -e .

# With NLP support (spaCy glossary detection) — requires Python 3.12 or 3.13 venv (see above)
pip install -e ".[nlp]"
spacy download en_core_web_md

# With LLM providers (OpenAI + Anthropic)
pip install -e ".[providers]"

# With SQLite persistence backend
pip install -e ".[sqlite]"

# Full — all extras
pip install -e ".[nlp,providers,sqlite]"

# uv equivalents (prefix with `uv pip`)
uv pip install -e ".[nlp,providers,sqlite]"
```

### Optional extras

| Extra | Installs | When needed |
|-------|----------|-------------|
| `nlp` | `spacy>=3.7.0` | Glossary-term detection in turn data — **create your venv with `py -3.13` or `py -3.12`** (spaCy is not yet compatible with Python 3.14+) |
| `providers` | `openai`, `anthropic` | Live LLM mode |
| `sqlite` | `sqlalchemy[asyncio]`, `aiosqlite` | SQLite persistence backend |
| `dev` | `pytest`, `pytest-cov` | Running the test suite |

## Primary LLM setup

The primary LLM handles all instructional, corrective, and high-weight
conversational turns. Two deployment modes are supported:

### Local provider (air-gapped / development / self-hosted)

`LUMINA_LLM_PROVIDER=local` connects to any OpenAI-compatible HTTP endpoint.
Supported local runtimes include **Ollama**, **vLLM**, **LM Studio**, **TGI**
(Text Generation Inference), and **OpenRouter** (local mode).

**Step 1 — Install a local runtime (Ollama example):**

```powershell
# Windows
winget install Ollama.Ollama
```

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh
```

**Step 2 — Pull a model:**

```bash
ollama pull llama3
```

**Step 3 — Start the runtime (if not running as a service):**

```bash
ollama serve
# Listens on http://localhost:11434 by default
```

**Step 4 — Set environment variables:**

```powershell
# PowerShell
$env:LUMINA_LLM_PROVIDER = "local"
$env:LUMINA_LLM_ENDPOINT = "http://localhost:11434"  # default
$env:LUMINA_LLM_MODEL    = "llama3"                  # default
$env:LUMINA_LLM_TIMEOUT  = "120"                     # seconds; increase on modest hardware
```

```bash
# POSIX
export LUMINA_LLM_PROVIDER=local
export LUMINA_LLM_ENDPOINT=http://localhost:11434
export LUMINA_LLM_MODEL=llama3
export LUMINA_LLM_TIMEOUT=120
```

### Primary LLM environment variable reference

| Variable | Default | Description |
|----------|---------|-------------|
| `LUMINA_LLM_PROVIDER` | `local` | Provider: `local`, `openai`, `anthropic`, `google`, `azure`, `mistral`; leave unset for deterministic mode |
| `LUMINA_LLM_ENDPOINT` | `http://localhost:11434` | Base URL for the local OpenAI-compatible endpoint; ignored for cloud providers |
| `LUMINA_LLM_MODEL` | `llama3` | Model name forwarded to the provider |
| `LUMINA_LLM_TIMEOUT` | `120` | HTTP timeout in seconds for local calls |

### Cloud providers

Install the `providers` extra, then set the appropriate API key:

```bash
pip install -e ".[providers]"
```

| Provider | Variable | Example model |
|----------|----------|---------------|
| `openai` | `OPENAI_API_KEY` | `gpt-4o` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-20241022` |
| `google` | `GOOGLE_API_KEY` | `gemini-1.5-pro` |
| `azure` | `AZURE_OPENAI_API_KEY` + `LUMINA_AZURE_OPENAI_ENDPOINT` + `LUMINA_AZURE_OPENAI_DEPLOYMENT` | depends on deployment |
| `mistral` | `MISTRAL_API_KEY` | `mistral-large-latest` |

Deterministic mode (no provider set, no API key required) is always available as a fallback.

## Authentication setup

Lumina uses a **dual-secret JWT architecture** that isolates admin-tier and
user-tier tokens at the cryptographic level. Three environment variables
control JWT signing:

| Variable | Required | Signed roles | `iss` claim |
|----------|----------|--------------|-------------|
| `LUMINA_JWT_SECRET` | Always | Legacy fallback for all tokens | `lumina` |
| `LUMINA_ADMIN_JWT_SECRET` | Production admin tier | `root`, `domain_authority`, `it_support` | `lumina-admin` |
| `LUMINA_USER_JWT_SECRET` | Production user tier | `user`, `qa`, `auditor`, `guest` | `lumina-user` |

When `LUMINA_ADMIN_JWT_SECRET` and `LUMINA_USER_JWT_SECRET` are both set,
admin-tier tokens are issued by `POST /api/admin/auth/login` and user-tier
tokens by `POST /api/auth/login`. The `iss` claim in each token selects the
correct secret for validation — the two tiers are cryptographically separated.
When only `LUMINA_JWT_SECRET` is set all tokens use it as a single shared
secret (development mode).

```bash
# Generate secrets
python -c "import secrets; print(secrets.token_hex(32))"
```

See [air-gapped-admin-architecture(8)](../8-admin/air-gapped-admin-architecture.md)
and [secrets-and-runtime-config(8)](../8-admin/secrets-and-runtime-config.md) for
production key-management guidance.

## SLM (Small Language Model) setup

The SLM layer routes low-weight tasks (glossary rendering, physics context compression, admin command translation) away from the primary LLM. See [slm-compute-distribution](../7-concepts/slm-compute-distribution.md) for the full architecture.

The SLM is **optional** — the system degrades gracefully to deterministic templates when it is unavailable. No SLM call ever blocks the primary chat pipeline.

### Local provider (default — recommended for development)

The local provider talks to any Ollama-compatible endpoint over HTTP. `httpx` is already installed as a core dependency; no additional Python package is needed.

**Step 1 — Install Ollama:**

```powershell
# Windows — download the installer from https://ollama.com/download
# or with winget:
winget install Ollama.Ollama
```

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh
```

**Step 2 — Pull the default model:**

```bash
ollama pull gemma3:4b
```

> `gemma3:4b` is the default SLM model (`LUMINA_SLM_MODEL=gemma3:4b`). Any model name pulled in Ollama can be used by setting `LUMINA_SLM_MODEL` to the same name.

**Step 3 — Start Ollama (if not already running as a background service):**

```bash
ollama serve
# Listens on http://localhost:11434 by default
```

**Step 4 — Verify the endpoint is reachable:**

```bash
# Should return HTTP 200
curl http://localhost:11434/

# Or from Python:
python -c "import httpx; r = httpx.get('http://localhost:11434/'); print(r.status_code)"
```

**Step 5 — (Optional) override the default model or port:**

```powershell
# PowerShell
$env:LUMINA_SLM_PROVIDER = "local"
$env:LUMINA_SLM_MODEL    = "gemma3:4b"                   # must match the name you pulled
$env:LUMINA_SLM_ENDPOINT = "http://localhost:11434"
```

```bash
# POSIX
export LUMINA_SLM_PROVIDER=local
export LUMINA_SLM_MODEL=gemma3:4b
export LUMINA_SLM_ENDPOINT=http://localhost:11434
```

### Cloud SLM providers

OpenAI and Anthropic can serve as the SLM backend using the same packages as the primary LLM. Install the `providers` extra if not already done:

```bash
pip install -e ".[providers]"
```

```bash
export LUMINA_SLM_PROVIDER=openai       # or: anthropic
export LUMINA_SLM_MODEL=gpt-4o-mini     # any model the SDK accepts
export OPENAI_API_KEY=<your-key>        # or ANTHROPIC_API_KEY
```

### SLM environment variable reference

| Variable | Default | Description |
|----------|---------|-------------|
| `LUMINA_SLM_PROVIDER` | `local` | Backend: `local`, `openai`, or `anthropic` |
| `LUMINA_SLM_MODEL` | `gemma3:4b` | Model name passed to the provider |
| `LUMINA_SLM_ENDPOINT` | `http://localhost:11434` | Ollama/llama.cpp base URL (local provider only) |
| `LUMINA_SLM_TIMEOUT` | `60` | HTTP timeout in seconds for local SLM calls. Increase on modest hardware if physics interpretation times out |

### Testing SLM operation end-to-end

With Ollama running and `gemma3:4b` pulled, start the API server and send a glossary query — the Librarian role should handle it via the SLM:

```powershell
# Terminal 1 — start the server
lumina-api

# Terminal 2 — log in and capture the token
$response = Invoke-RestMethod -Uri 'http://localhost:8000/api/auth/login' `
  -Method POST -ContentType 'application/json' `
  -Body '{"username":"admin","password":"<pw>"}'
$token = $response.token

# Send a glossary query
Invoke-RestMethod -Uri 'http://localhost:8000/api/chat' `
  -Method POST -ContentType 'application/json' `
  -Headers @{ Authorization = "Bearer $token" } `
  -Body '{"session_id":"slm-test-1","message":"what is equivalence?"}'
```

When the SLM is active the definition response is more fluent than the bare `"{term}: {definition}"` deterministic fallback. Check server logs for `[lumina.core.slm]` lines — the absence of `SLM unavailable` warnings confirms the SLM handled the request.

To verify weight-routed dispatch more directly: send any message that triggers a `definition_lookup` action and confirm `"prompt_type": "definition_lookup"` in the JSON response. LOW-weight prompt types are routed to the SLM; all instructional/corrective types go to the primary LLM.

### Fallback behaviour

If Ollama is not running or `gemma3:4b` is not pulled, **the server continues to operate normally**. Glossary responses fall back to the `"{term}: {definition}"` deterministic template, physics context compression is skipped, and admin command translation returns HTTP 503. No error is surfaced to the end user. The `[lumina.core.slm]` logger emits a `WARNING` level entry for each skipped SLM call.

## CLI entrypoints

Available after editable install:

```bash
lumina-api                # start the FastAPI server
lumina-verify             # repo integrity check
lumina-orchestrator-demo  # run the deterministic orchestrator demo
lumina-system-log-validate       # validate a System Log commitment record
lumina-security-freeze    # check for exposed secrets / security hygiene
lumina-yaml-convert       # convert YAML files to JSON
```

`lumina-api` starts the FastAPI server on `LUMINA_PORT` (default: `8000`).
For the complete endpoint reference, all environment variables, and
authentication details see [lumina-api-server(2)](../2-syscalls/lumina-api-server.md).

## Frontend (src/web)

The reference UI is a Vite + React + TypeScript app located in `src/web/`. Node.js 20+ is required.

```bash
cd src/web
npm install
```

### Dev server

```bash
npm run dev
# Starts on http://localhost:5173 by default
```

The dev server proxies API requests to the Lumina backend. Start the backend first:

```bash
# In a separate terminal (repo root)
lumina-api    # or: python -m lumina.api.server
```

### Production build

```bash
npm run build
# Output written to src/web/dist/
npm run preview    # serves the built output locally
```

### Frontend tests

```bash
npm run test:unit      # Vitest unit tests
npm run test:coverage  # unit tests + coverage report (src/web/coverage/)
npm run test:e2e       # Playwright e2e smoke tests (requires a running backend)
```

---

## PowerShell utility scripts

All scripts in `scripts/` require a Python interpreter. By default they look for
`.\.venv\Scripts\python.exe` relative to the repo root. If that path does not exist
you will see:

```
Python executable not found at: .\.venv\Scripts\python.exe
```

**Fix:** create the virtual environment and install the package first:

```powershell
# From the repo root
python -m venv .venv          # standard
# -- or --
uv venv                       # uv

.\.venv\Scripts\pip install -e ".[dev]"
```

Every script also accepts a `-PythonExe` parameter so you can point at any Python
installation without a venv:

```powershell
.\scripts\<script>.ps1 -PythonExe "C:\Python312\python.exe"
```

### seed-system-physics-log.ps1

Computes the canonical SHA-256 of `cfg/system-physics.json` and writes a
`system_physics_activation` CommitmentRecord to the System Log
(`$LUMINA_LOG_DIR/system/system.jsonl`). Safe to run multiple times — idempotent
if the hash is already committed.

Run this whenever `cfg/system-physics.yaml` is edited and recompiled. The server
will refuse to start until the active hash is committed.

The System Log directory is resolved from the `-LogDir` parameter, then from
`LUMINA_LOG_DIR` (primary), then `LUMINA_CTL_DIR` (backward-compat fallback),
then a temp directory. Set `LUMINA_LOG_DIR` in production.

```powershell
# Default (uses .venv, LUMINA_LOG_DIR from environment)
.\scripts\seed-system-physics-log.ps1

# Custom actor and System Log directory
.\scripts\seed-system-physics-log.ps1 `
    -ActorId "ci-pipeline" `
    -LogDir "C:\lumina-data\system-log"

# Custom Python
.\scripts\seed-system-physics-log.ps1 -PythonExe "C:\Python312\python.exe"
```

See [system-domain-operations](../8-admin/system-domain-operations.md) for the
full system-physics activation workflow.

| Variable | Description |
|----------|-------------|
| `LUMINA_LOG_DIR` | Primary System Log root directory |
| `LUMINA_CTL_DIR` | Backward-compatible fallback (deprecated — prefer `LUMINA_LOG_DIR`) |

### integrity-check.ps1

Verifies SHA-256 hashes for all core artifacts listed in `docs/MANIFEST.yaml`.
Exits 0 when all recorded hashes match; exits 1 on any MISMATCH (hash changed).
PENDING and MISSING entries produce warnings but do not fail the check.

```powershell
.\scripts\integrity-check.ps1
.\scripts\integrity-check.ps1 -PythonExe "C:\Python312\python.exe"
```

---

## SEE ALSO

- [lumina-api-server(2)](../2-syscalls/lumina-api-server.md) — full endpoint and environment variable reference
- [secrets-and-runtime-config(8)](../8-admin/secrets-and-runtime-config.md) — production secret management and runtime modes
- [air-gapped-admin-architecture(8)](../8-admin/air-gapped-admin-architecture.md) — dual JWT air-gap architecture
- [slm-compute-distribution(7)](../7-concepts/slm-compute-distribution.md) — SLM routing architecture and weight classification
```

### manifest-regenerate.ps1

Recomputes and rewrites SHA-256 hashes in `docs/MANIFEST.yaml` in-place. Run
after modifying any artifact listed in the manifest, or when `integrity-check.ps1`
reports a MISMATCH.

```powershell
.\scripts\manifest-regenerate.ps1
.\scripts\manifest-regenerate.ps1 -PythonExe "C:\Python312\python.exe"
```

### run-full-verification.ps1

End-to-end verification pipeline: secret hygiene, repo integrity, manifest
integrity, orchestrator demo, frontend build, and pre-integration API scenarios.
Intended for CI and pre-merge local validation.

```powershell
# Full run
.\scripts\run-full-verification.ps1

# Skip slow steps
.\scripts\run-full-verification.ps1 -SkipFrontend -SkipOrchestratorDemo

# Custom Python and API base URL
.\scripts\run-full-verification.ps1 `
    -PythonExe "C:\Python312\python.exe" `
    -ApiBaseUrl "http://127.0.0.1:9000"
```
