# Contributing to Project Lumina

Welcome, and thank you for your interest in Project Lumina.

Lumina is not a chatbot; it is a **domain-bounded, measurement-centric AI orchestration framework**. Our core philosophy is **Accountability by Design**. Every contribution must uphold the integrity of the **D.S.A. (Domain, State, Action)** prompt contracts and the cryptographic accountability of the **System Logs**.

Whether you are optimizing the core orchestration engine or authoring a new domain pack, please read this guide carefully to understand our strict architectural boundaries.

---

## 🏗️ Architectural Boundaries

Before contributing, you must understand the firewall between the core engine and the domain packs.

### 1. The Core Engine (`reference-implementations/`)

The core orchestrator (`lumina-api-server.py`, `dsa-orchestrator.py`) is **100% domain-agnostic**.

* **Zero Domain Logic:** You may not hardcode rules, prompts, or assumptions about specific subjects (e.g., education, medical, agriculture) into the core engine.
* **Contract Enforcement:** The engine's only job is to assemble the dynamic prompt contract, execute it, verify the tool/invariant outputs, and log the state change to the System Logs.

### 2. Domain Packs (`domain-packs/`)

All domain-specific behavior lives here. If you are adding a new use case, you are authoring a Domain Pack.

* You must define the rules of reality in a `domain-physics.yaml` or `.json` file.
* You must provide a complete `runtime-config.yaml` to map actions to your specific Python tool adapters.
* **Fractal Authority:** Your domain pack must clearly define its governance levels (Macro → Meso → Micro → Target).
* **Runtime Adapter:** You must implement `controllers/runtime_adapters.py` with an `interpret_turn_input` function. All domain-specific signal computation — including engine contract fields like `problem_solved` and `problem_status` — must be computed here. These fields must never be hardcoded or evaluated inside `src/lumina/`. See [`docs/7-concepts/domain-adapter-pattern.md`](docs/7-concepts/domain-adapter-pattern.md) for the complete authoring pattern, engine contract field catalogue, and examples covering both single-step and multi-step task domains (e.g., a 15-step procedural task produces `problem_status = "step_N_of_15_complete"` on each turn and sets `problem_solved = True` on the final step).

---

## 🛠️ How to Contribute

### Adding or Modifying a Domain Pack

We welcome new reference implementations for different industries. To submit a new domain pack, your PR must include:

1. **`runtime-config.yaml`:** The ownership surface mapping actions to tools.
2. **Prompts:** A `domain-system-override.md` and `turn-interpretation.md`.
3. **Schemas:** JSON schemas defining the compressed state and subject profile.
4. **Tool Adapters:** Python functions that deterministically verify the LLM's proposals.
5. **Pre-integration Scenarios:** A standalone script or set of JSON payloads proving your domain rules work under stress.

### Modifying the Core Engine or System Log

Changes to the orchestration loop or the System Logs are high-risk and require heavy validation.

1. **System Log Integrity:** Your change cannot break the append-only hash-chain. Every engine decision must result in a valid `TraceEvent` or `EscalationRecord`.
2. **Backward Compatibility:** Core changes must be tested against *all* existing domain packs in the repository to prove they haven't introduced domain bias.

---

## 🧪 Testing and Regression (Mandatory)

We do not merge code based on "vibes" or isolated live LLM testing. You must prove your changes mathematically using our deterministic test suite.

Before submitting a Pull Request, run the pre-integration scenarios:

**Windows (PowerShell):**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\reference-implementations\run-preintegration-scenarios.ps1 -BaseUrl "http://localhost:8000"

```

**What the tests check:**

* Health check and stable turn execution.
* **Major Drift Simulation:** Ensures the orchestrator successfully catches a boundary violation and triggers a Hard Escalation.
* **System Log Hash-Chain Integrity:** Validates that no trace events were dropped or mutated.

**If the deterministic test suite fails, your PR will be automatically rejected.**

---

## 📝 Pull Request Process

1. **Fork the repository** and create your feature branch: `git checkout -b feature/your-feature-name`.
2. **Write deterministic tests** for any new tool adapters or core engine logic.
3. **Run the regression suite** (see above).
4. **Commit your changes.** Use clear, descriptive commit messages.
5. **Open a PR** against the `main` branch.
6. **Include Proof:** In your PR description, you must include a sample `trace-event-schema.json` output demonstrating that your feature is properly logging its execution to the System Logs.

---

## ⚖️ Core Principles Check

Before you push, ask yourself:

* *Did I expand the scope of the AI without adding an explicit drift justification requirement?*
* *Did I store any PII or chat transcripts instead of pseudonymized structured state?*
* *Did I bypass the Domain Authority's explicit rules?*

If the answer to any of these is yes, revise your code. We build for accountability.
