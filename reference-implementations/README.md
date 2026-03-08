# Reference Implementations — Project Lumina

This directory contains Python reference implementations of the **core D.S.A. engine** components. Education-domain-specific implementations (ZPD monitor) live in [`../domain-packs/education/reference-implementations/`](../domain-packs/education/reference-implementations/).

---

## Contents

| File | Description |
|------|-------------|
| `yaml-loader.py` | Domain-agnostic minimal YAML loader (standard library only) |
| `yaml-to-json-converter.py` | Converts and validates domain pack YAML → JSON |
| `ctl-commitment-validator.py` | CTL hash chain validator and commitment recorder |
| `dsa-orchestrator.py` | D.S.A. orchestrator: domain-agnostic invariant evaluation + CTL + prompt contract |
| `dsa-orchestrator-demo.py` | End-to-end demo of the full D.S.A. Action loop wired to the education domain (10-turn scripted session) |
| `runtime_loader.py` | Runtime config loader and adapter wiring validator |
| `lumina-api-server.py` | FastAPI integration host for `/api/chat`, health, and CTL validation routes |
| `persistence_adapter.py` | Domain-agnostic persistence adapter interface |
| `filesystem_persistence.py` | Filesystem-backed persistence adapter (default behavior) |
| `sqlite_persistence.py` | SQLite persistence adapter (optional; SQLAlchemy async) |
| `verify-repo-integrity.py` | Repo-level integrity checks (links, runtime paths, version alignment, frontend essentials) |
| `run-full-verification.ps1` | One-command verification flow (integrity + orchestrator + frontend + optional API scenarios) |

---

## Requirements

Python 3.10+ is required. Core demos remain standard-library-first. The SQLite persistence backend is optional and requires external dependencies.

```bash
python --version  # Requires 3.10+
```

Optional SQLite persistence dependencies:

```bash
pip install "sqlalchemy[asyncio]" aiosqlite
```

---

## Quick Start

### Run the ZPD monitor demo (education domain)

```bash
python domain-packs/education/reference-implementations/zpd-monitor-demo.py
```

### Run the D.S.A. orchestrator demo (full loop)

```bash
python reference-implementations/dsa-orchestrator-demo.py
```

### Convert and validate a domain pack

```bash
python reference-implementations/yaml-to-json-converter.py \
  domain-packs/education/algebra-level-1/domain-physics.yaml \
  --schema standards/domain-physics-schema-v1.json
```

### Verify a CTL hash chain

```bash
python reference-implementations/ctl-commitment-validator.py \
  --verify-chain path/to/ledger.jsonl
```

### Run repo integrity checks

```bash
python reference-implementations/verify-repo-integrity.py
```

### Run full verification flow

```powershell
./reference-implementations/run-full-verification.ps1
```

The script now auto-starts `lumina-api-server.py` for pre-integration scenarios if `/api/health` is not reachable at `-ApiBaseUrl`.

Useful options:

```powershell
./reference-implementations/run-full-verification.ps1 -SkipOrchestratorDemo
./reference-implementations/run-full-verification.ps1 -SkipFrontend
```

If you want to skip API scenario calls entirely:

```powershell
./reference-implementations/run-full-verification.ps1 -SkipApiScenarios
```

### Validate CTL via API

```bash
# Validate all known sessions
curl http://localhost:8000/api/ctl/validate

# Validate one session
curl "http://localhost:8000/api/ctl/validate?session_id=<session-uuid>"
```

When `LUMINA_PERSISTENCE_BACKEND=sqlite`, CTL append-only semantics are also enforced by DB triggers that reject `UPDATE` and `DELETE` on `ctl_records`.

### Commit a domain pack hash to the CTL

```bash
python reference-implementations/ctl-commitment-validator.py \
  --commit domain-packs/education/algebra-level-1/domain-physics.json \
  --actor-id <pseudonymous-id> \
  --ledger path/to/ledger.jsonl
```

---

## Design Philosophy

All reference implementations:
- Use **deterministic heuristics only** — no ML, no probabilistic models
- Use **only Python standard library** — no external dependencies
- Are **readable by a Domain Authority** — the logic should be transparent enough that a domain expert can understand why the system made a decision
- Are **not production code** — they are reference implementations for understanding and testing

---

## Relationship to Specs

| Implementation | Spec |
|---------------|------|
| `yaml-loader.py` | (utility — no dedicated spec) |
| `yaml-to-json-converter.py` | [`../specs/domain-profile-spec-v1.md`](../specs/domain-profile-spec-v1.md) |
| `ctl-commitment-validator.py` | [`../standards/causal-trace-ledger-v1.md`](../standards/causal-trace-ledger-v1.md) |
| `dsa-orchestrator.py` | [`../specs/dsa-framework-v1.md`](../specs/dsa-framework-v1.md) |
| `dsa-orchestrator.py` | [`../specs/orchestrator-system-prompt-v1.md`](../specs/orchestrator-system-prompt-v1.md) |
| `dsa-orchestrator-demo.py` | [`../specs/dsa-framework-v1.md`](../specs/dsa-framework-v1.md) |

See [`../domain-packs/education/reference-implementations/README.md`](../domain-packs/education/reference-implementations/README.md) for education-domain-specific implementations.
