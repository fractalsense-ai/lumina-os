# Lumina OS

**A deterministic orchestration OS for domain-bounded AI systems.**

> TCP/IP assembles packets from layered protocols. Lumina OS does the same thing for LLMs — assembling structured prompt contracts from immutable domain rules, mutable state, and actor evidence, then verifying every output before it reaches the user.

---

## Screenshots



[Verbose CLI output](screenshots/cli-verbose.png)
[Chat interface](screenshots/chat-interface.png)


---

## What Is Lumina OS?

Lumina OS is a **zero-trust orchestration layer** that wraps any LLM in deterministic contracts. The LLM is the **processing unit**, not the authority. Everything surrounding it — input normalization, prompt assembly, output verification, and audit logging — is **deterministic and verifiable**.

Three properties define the system:

1. **Prompt injection is structurally mitigated** — the LLM receives the user's raw input, but never in isolation. All input passes through an inspection middleware pipeline (NLP extraction → schema validation → invariant checking) before the prompt contract is assembled. The model sees the original message embedded inside a deterministic contract — domain physics, actor identity, state context, and a sliding window of recent turns — so it cannot be manipulated by the input alone.

2. **Hallucinations are traceable** — every LLM output passes through deterministic tool-adapter verification. Unrecognized patterns trigger a two-key gate: the LLM flags it, then a human Domain Authority confirms or rejects. The append-only System Log records `model_id`, `model_version`, and the verdict for every decision.

3. **Every output is gated** — no LLM response reaches the user without passing through deterministic verification. Violations escalate to a human. Novel synthesis events require explicit Domain Authority approval.

The core engine is **fully domain-agnostic**. All domain behavior — prompts, state models, tool adapters, and templates — lives in self-contained **domain packs** loaded at runtime. No server code changes are needed to switch domains.

---

## The D.S.A. Framework

Every session contract is built on three structural pillars:

| Pillar | Name | Role | Mutability |
|--------|------|------|------------|
| **D** | Domain | Immutable rules, invariants, standing orders, escalation triggers | Immutable per session |
| **S** | State | Compact entity profile updated from structured evidence | Mutable |
| **A** | Actor | Evidence-producing entity (student, sensor, operator, device) | Identified per session |

The orchestrator's response is derived from all three pillars — it is not itself a pillar. The orchestrator is an **executor and translator**: it observes incoming evidence, updates State, checks Domain invariants, selects a response within standing orders, and escalates when it cannot stabilize.

**Decision tiers** control how the orchestrator responds:

| Tier | Condition | Action |
|------|-----------|--------|
| `ok` | All invariants pass | Respond within standing orders |
| `minor` | Soft invariant triggered | Apply standing order correction |
| `major` | Hard invariant triggered | Escalate to Domain Authority |
| `escalate` | Cannot stabilize | Human-in-the-loop required |

> The LLM is the processing unit, not the authority.

See [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) for the full D.S.A. specification.

---

## Prompt Packet Assembly (PPA)

Like TCP/IP, PPA assembles a packet from layered components — each layer adds its headers, the payload travels through, and verification confirms integrity:

```
┌────────────────────────────────────────────────────┐
│  Input Interface (chat, sensor, API)               │
├────────────────────────────────────────────────────┤
│  Inspection Middleware                              │  ← NLP extraction → schema validation → invariant check
├────────────────────────────────────────────────────┤
│  SLM Pre-Interpreter                               │  ← pre-digests domain physics → compressed context
├────────────────────────────────────────────────────┤
│  Global Base Prompt                                 │  ← universal rules (like IP headers)
├────────────────────────────────────────────────────┤
│  Domain Physics                                     │  ← immutable domain-specific policy
├────────────────────────────────────────────────────┤
│  Module State + Turn Data                           │  ← session context + NLP anchors
├════════════════════════════════════════════════════╡
│  Assembled Prompt Contract                          │  ← the "packet" ready for dispatch
├────────────────────────────────────────────────────┤
│  Task Weight Classifier                             │  ← LOW → SLM | HIGH → LLM
├────────────────────────────────────────────────────┤
│  Tool-Adapter Verification                          │  ← deterministic output checking
├────────────────────────────────────────────────────┤
│  System Log                                         │  ← append-only audit ledger
└────────────────────────────────────────────────────┘
```

The LLM does not have to guess about context — it receives exactly the contract it needs, nothing more.

See [`docs/7-concepts/prompt-packet-assembly.md`](docs/7-concepts/prompt-packet-assembly.md) for the full layer reference.

---

## Slash Commands

Slash commands **bypass the language model entirely**. They are deterministic operations that go through schema validation, RBAC enforcement, and audit logging — no LLM involved at any stage.

Three tiers of commands exist:

| Tier | Examples | Gate |
|------|----------|------|
| **User** | `/status`, `/glossary`, `/history` | Session-scoped |
| **Domain** | `/add-term`, `/update-physics` | Domain Authority |
| **Admin** | `/escalate`, `/override`, `/audit` | RBAC + HITL confirmation |

The execution path:

1. **Input** → recognized as slash command (prefix match)
2. **Schema validation** → command payload validated against admin-command-schema
3. **RBAC check** → caller's role verified against command's required tier
4. **Execution** → deterministic handler (no LLM)
5. **System Log** → action recorded to append-only audit ledger

For natural-language admin instructions (e.g., "add 'photosynthesis' to the glossary"), the **SLM Command Translator** parses the intent into a structured operation. The SLM is a small language model used for structured extraction — it is not the reasoning LLM. The operation then follows the same deterministic path above.

See [`docs/1-commands/`](docs/1-commands/README.md) for the full command reference.

---

## Quick Start

### Prerequisites

- Python 3.12+ (tested on 3.13)
- An LLM API key (OpenAI or Anthropic) — only required for live responses

### Install and run (deterministic mode — no API key needed)

```bash
# Create a virtual environment
python3 -m venv .venv && source .venv/bin/activate
# Windows: py -3.13 -m venv .venv && .venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Set the runtime config
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/education/cfg/runtime-config.yaml"
# Windows: $env:LUMINA_RUNTIME_CONFIG_PATH="domain-packs/education/cfg/runtime-config.yaml"

# Start the server
python -m lumina.api.server

# Send a deterministic request (no LLM needed)
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I solved it and checked by substitution.", "deterministic_response": true}'
```

### Enable a live LLM

```bash
export OPENAI_API_KEY="sk-..."
pip install openai
# Then send requests without deterministic_response
```

### Run tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

See [`docs/1-commands/installation-and-packaging.md`](docs/1-commands/installation-and-packaging.md) for detailed setup and [`docs/8-admin/secrets-and-runtime-config.md`](docs/8-admin/secrets-and-runtime-config.md) for production config.

---

## Repository Structure

```
lumina-os/
├── src/lumina/           ← core engine (API, orchestrator, middleware, persistence, system log)
├── src/web/              ← Vite + React reference UI
├── domain-packs/         ← self-contained domain knowledge + behavior
│   ├── education/        ← algebra, world-sim, MUD builder
│   ├── agriculture/      ← sensor ops, group library reference implementation
│   └── system/           ← SLM-only routing, no external LLM
├── specs/                ← formal specifications (DSA, principles, RBAC)
├── standards/            ← JSON schemas and conformance standards
├── docs/                 ← UNIX man-page reference (sections 1–8)
├── tests/                ← pytest suite (3690+ tests)
├── scripts/              ← build, integrity, migration, and verification tools
└── data/                 ← retrieval indices, profiles, blackbox snapshots
```

---

## Documentation

Full reference documentation follows the UNIX man-page section convention:

| Section | Name | Contents |
|---------|------|----------|
| [1](docs/1-commands/) | Commands | CLI tools and utilities |
| [2](docs/2-syscalls/) | System Calls | API endpoints and server interface |
| [3](docs/3-functions/) | Functions | Library interfaces (auth, persistence) |
| [4](docs/4-formats/) | Formats | JSON schemas and data structures |
| [5](docs/5-standards/) | Standards | Core specifications and protocols |
| [6](docs/6-examples/) | Examples | Worked interaction traces |
| [7](docs/7-concepts/) | Concepts | Architecture and design philosophy |
| [8](docs/8-admin/) | Administration | Governance, RBAC, audit, operations |

All artifacts are versioned with semver headers, status fields, and SHA-256 integrity records. See [`docs/MANIFEST.yaml`](docs/MANIFEST.yaml) for the machine-readable artifact index.

---

## Conformance

All domain packs and implementations must conform to [`standards/lumina-core-v1.md`](standards/lumina-core-v1.md). See [`docs/5-standards/`](docs/5-standards/README.md) for the full specification index.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

## Disclaimer

Lumina OS is research/experimental software provided AS-IS under Apache 2.0 with NO WARRANTIES. No part of this project is certified for safety-critical, high-stakes, or regulated use (including with minors) without thorough independent validation.

The engine provides structural accountability (D.S.A. contracts, System Log traces) but does **not** replace human oversight, professional judgment, or legal compliance. Ultimate accountability sits with the human Domain Authority at each level, never the AI or the engine.

---

*Last updated: 2026-04-16*
