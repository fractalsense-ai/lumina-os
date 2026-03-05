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

---

## Requirements

Python 3.10+ is required. No external dependencies beyond the standard library.

```bash
python --version  # Requires 3.10+
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
