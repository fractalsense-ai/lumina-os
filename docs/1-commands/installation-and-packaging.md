# installation-and-packaging

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

Installation and packaging workflows for Project Lumina.

Before running live LLM mode, configure runtime secrets and environment settings: [secrets-and-runtime-config](../8-admin/secrets-and-runtime-config.md).

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
spacy download en_core_web_sm

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
ollama pull phi3
```

> `phi3` maps to `LUMINA_SLM_MODEL=phi-3` (the default). Any model name pulled in Ollama can be used by setting `LUMINA_SLM_MODEL` to the same name.

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
$env:LUMINA_SLM_MODEL    = "phi3"                   # must match the name you pulled
$env:LUMINA_SLM_ENDPOINT = "http://localhost:11434"
```

```bash
# POSIX
export LUMINA_SLM_PROVIDER=local
export LUMINA_SLM_MODEL=phi3
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
| `LUMINA_SLM_MODEL` | `phi-3` | Model name passed to the provider |
| `LUMINA_SLM_ENDPOINT` | `http://localhost:11434` | Ollama/llama.cpp base URL (local provider only) |

### Testing SLM operation end-to-end

With Ollama running and `phi3` pulled, start the API server and send a glossary query — the Librarian role should handle it via the SLM:

```bash
# Terminal 1 — start the server
lumina-api

# Terminal 2 — log in
curl -sX POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<pw>"}' | python -m json.tool

# Send a glossary query (replace <token> with the access_token from login)
curl -sX POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"session_id":"slm-test-1","message":"what is equivalence?"}' | python -m json.tool
```

When the SLM is active the definition response is more fluent than the bare `"{term}: {definition}"` deterministic fallback. Check server logs for `[lumina.core.slm]` lines — the absence of `SLM unavailable` warnings confirms the SLM handled the request.

To verify weight-routed dispatch more directly: send any message that triggers a `definition_lookup` action and confirm `"prompt_type": "definition_lookup"` in the JSON response. LOW-weight prompt types are routed to the SLM; all instructional/corrective types go to the primary LLM.

### Fallback behaviour

If Ollama is not running or `phi3` is not pulled, **the server continues to operate normally**. Glossary responses fall back to the `"{term}: {definition}"` deterministic template, physics context compression is skipped, and admin command translation returns HTTP 503. No error is surfaced to the end user. The `[lumina.core.slm]` logger emits a `WARNING` level entry for each skipped SLM call.

## CLI entrypoints

Available after editable install:

```bash
lumina-api                # start the FastAPI server
lumina-verify             # repo integrity check
lumina-orchestrator-demo  # run the deterministic orchestrator demo
lumina-ctl-validate       # validate a CTL commitment record
lumina-security-freeze    # check for exposed secrets / security hygiene
lumina-yaml-convert       # convert YAML files to JSON
```

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

### seed-system-physics-ctl.ps1

Computes the canonical SHA-256 of `cfg/system-physics.json` and writes a
`system_physics_activation` CommitmentRecord to the system CTL
(`$LUMINA_CTL_DIR/system/system.jsonl`). Safe to run multiple times — idempotent
if the hash is already committed.

Run this whenever `cfg/system-physics.yaml` is edited and recompiled. The server
will refuse to start until the active hash is committed.

```powershell
# Default (uses .venv)
.\scripts\seed-system-physics-ctl.ps1

# Custom actor and CTL directory
.\scripts\seed-system-physics-ctl.ps1 `
    -ActorId "ci-pipeline" `
    -CtlDir "C:\lumina-data\ctl"

# Custom Python
.\scripts\seed-system-physics-ctl.ps1 -PythonExe "C:\Python312\python.exe"
```

See [system-domain-operations](../8-admin/system-domain-operations.md) for the
full system-physics activation workflow.

### integrity-check.ps1

Verifies SHA-256 hashes for all core artifacts listed in `docs/MANIFEST.yaml`.
Exits 0 when all recorded hashes match; exits 1 on any MISMATCH (hash changed).
PENDING and MISSING entries produce warnings but do not fail the check.

```powershell
.\scripts\integrity-check.ps1
.\scripts\integrity-check.ps1 -PythonExe "C:\Python312\python.exe"
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
