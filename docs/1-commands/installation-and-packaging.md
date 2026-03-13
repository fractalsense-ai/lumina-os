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

```bash
# Minimal (FastAPI + uvicorn only)
python -m pip install -e .

# With NLP support (spaCy glossary detection) — Python 3.12/3.13 only
python -m pip install -e ".[nlp]"
python -m spacy download en_core_web_sm

# With LLM providers (OpenAI + Anthropic)
python -m pip install -e ".[providers]"

# With SQLite persistence backend
python -m pip install -e ".[sqlite]"

# Full — all extras
python -m pip install -e ".[nlp,providers,sqlite]"

# uv equivalents (prefix with `uv pip`)
uv pip install -e ".[nlp,providers,sqlite]"
```

### Optional extras

| Extra | Installs | When needed |
|-------|----------|-------------|
| `nlp` | `spacy>=3.7.0` | Glossary-term detection in turn data — **requires Python 3.12 or 3.13** (spaCy is not yet compatible with Python 3.14+) |
| `providers` | `openai`, `anthropic` | Live LLM mode |
| `sqlite` | `sqlalchemy[asyncio]`, `aiosqlite` | SQLite persistence backend |
| `dev` | `pytest`, `pytest-cov` | Running the test suite |

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
