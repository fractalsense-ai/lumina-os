# Domain Adapter Pattern

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

This document explains how domain packs extend the core engine's behaviour without modifying it. It is the canonical reference for any author adding computed signals, NLP pre-processing, or multi-step task logic to a new domain pack.

---

## A. The Engine Contract

The core engine (`src/lumina/api/server.py`) reads a small set of **well-known generic fields** from `turn_data` after each turn. These fields are called **engine contract fields**. The engine never inspects domain-specific field names — it only reads these reserved names and acts on their values.

This is the hard invariant:

> **Zero domain-specific names may appear in `src/lumina/`.** All domain logic, domain field names, and domain computations live exclusively in the domain pack.

What varies completely between domains is *how* the runtime adapter computes those contract fields. An education adapter might say "the problem is solved when the algebra parser confirms the substitution." A mass-spectrometry lab adapter might say "the task is complete when all 15 verified procedural steps have been logged." The core engine sees only `problem_solved: true` — the reasoning behind it stays in the domain pack.

---

## B. Engine Contract Field Reference

These are the fields the core engine reads by name from `turn_data`. Every domain pack that wants the associated engine behaviour must populate them in its runtime adapter.

| Field | Type | Default | What the engine does with it |
|---|---|---|---|
| `problem_solved` | `bool` | `false` | When `True`, fires the **problem-advancement gate** — the engine generates the next task using the domain's `generate_problem` tool function |
| `problem_status` | `str` | `""` | When non-empty, writes to `current_problem["status"]` — lets the adapter tag the running lifecycle state of the current task (e.g. `"step_3_of_15_complete"`, `"in_progress"`) |

### Usage pattern

These two fields are complementary for multi-step tasks. On each turn the adapter sets `problem_status` to a progress marker. On the final successful turn it also sets `problem_solved = True`, which triggers the engine to retire the current task and present the next one.

**Education example** — single verification step:
```python
evidence["problem_solved"] = (
    evidence.get("correctness") == "correct"
    and evidence.get("substitution_check") is True
    and evidence.get("step_count", 0) >= evidence.get("min_steps", 1)
)
```

**Hypothetical mass-spec example** — 15-step procedural task:
```python
steps_done = evidence.get("verified_step_count", 0)
evidence["problem_status"] = f"step_{steps_done}_of_15_complete"
evidence["problem_solved"] = steps_done >= 15
```

Both examples live entirely in their respective domain packs. The engine sees the same two field names regardless of domain.

---

## C. The Three-Layer Distinction

Domain packs are authors of three distinct types of components. These are often confused; understanding the distinction is essential before writing a runtime adapter.

### 1. Tool Adapters (`systools/tool_adapters.py` or `modules/<module>/tool-adapters/`)

**Active verifiers** that produce structured data on demand. There are two kinds:

- **Policy-driven tool adapters** — declared in YAML under `modules/<module>/tool-adapters/` and registered in `cfg/runtime-config.yaml` under `tool_call_policies`. Called by the core engine's policy system (`apply_tool_call_policy`) on specific resolved actions.
- **Direct tool adapters** — defined in `systools/tool_adapters.py` and registered in `cfg/runtime-config.yaml` under `adapters.tools`. Called directly by the runtime adapter (or by operator tooling) rather than by the orchestrator's policy system. Used for read-only data retrieval where policy-level gating is unnecessary.

In both cases:
- Should be **pure and deterministic**: same inputs → same outputs
- Must take `payload: dict` and return `dict`
- Must not import from `src/lumina/` (keeps the domain pack self-contained)

### 2. Domain Library (`domain-lib/`)

**Passive state estimators** that track entity state across turns — e.g., ZPD monitor, fluency tracker, fatigue model. They are implemented as Python classes/functions and called **inside the runtime adapter** (`domain_step` in `runtime_adapters.py`). They are never called directly by the core engine.

- Specifications live in `domain-lib/*.md`
- Implementations live in `systools/*.py`
- Called **by the runtime adapter**, not the orchestrator
- Produce state transitions (e.g., fluency `advanced: True`) that the adapter then uses to populate engine contract fields

### 3. Runtime Adapter (`systools/runtime_adapters.py`)

The **synthesis layer** — the domain pack's primary integration point with the core engine. It owns two phases of work on every turn:

- **Phase A:** NLP pre-processing (before the LLM turn)
- **Phase B:** Signal synthesis (after all tool and domain-lib results are in)

The adapter can call into domain-lib components and invoke tool functions directly (not via policy). Its output is the `evidence` dict, which the engine reads for invariant evaluation, action resolution, and engine contract field consumption.

---

## D. Phase A — NLP Pre-Processing

Phase A runs on the raw user message **before** the LLM prompt is assembled. Its job is to extract deterministic structured signals from unstructured text and inject them as grounding anchors into the LLM prompt context — making turn interpretation more reliable and reducing LLM hallucination of factual fields.

The NLP pre-interpreter is registered at startup via `cfg/runtime-config.yaml`:

```yaml
nlp_pre_interpreter_fn: nlp_preprocess   # function in systools/nlp_pre_interpreter.py
```

And called from the main server via `runtime.get("nlp_pre_interpreter_fn")` before passing control to `interpreter(**kwargs)` in `runtime_adapters.interpret_turn_input`.

### What the education pre-interpreter extracts

| Extractor | Output fields | Method |
|---|---|---|
| `extract_answer_match` | `correctness` (correct/incorrect), `extracted_answer` | Regex patterns for `x = N`, "answer is N", bare number |
| `extract_frustration_markers` | `frustration_marker_count`, `markers` | Keyword regex, ALL_CAPS ratio, excessive punctuation |
| `extract_hint_request` | `hint_used` | Keyword regex ("help me", "I'm stuck", "give me a hint") |
| `extract_off_task_ratio` | `off_task_ratio` | Math vocabulary overlap as a ratio of total tokens |

Extracted values are returned as a partial `evidence` dict plus a `_nlp_anchors` metadata list. The anchors are formatted into natural-language lines and prepended to the LLM context hint, tagged as deterministic:

```
NLP pre-analysis (deterministic):
- correctness: correct (confidence: 0.95) — matched answer "4" to expected "x = 4"
- frustration_marker_count: 0
- off_task_ratio: 0.1
Use these as starting values. Override if your analysis disagrees.
```

The LLM may override them, but having deterministic anchors as a prior makes overrides the exception rather than the rule.

### Adding a new Phase A extractor

1. Write a pure function in your domain's `systools/nlp_pre_interpreter.py` that takes `input_text: str` and returns a `dict`.
2. Call it inside `nlp_preprocess()` and add the result to `evidence` and `anchors`.
3. Register the output field in `cfg/runtime-config.yaml` under `turn_input_defaults` and `turn_input_schema`.
4. Nothing in `src/lumina/` needs to change.

---

## E. Phase B — Signal Synthesis (Step-by-Step Template)

Phase B runs at the **end of `interpret_turn_input()`**, after the LLM has produced the base evidence dict and after any tool adapter overrides (algebra parser, etc.) have been applied. Its job is to compute the engine contract fields that the core engine will act on.

### Template for adding a new computed gate signal

**Step 1 — Define the field in `cfg/runtime-config.yaml`**

Add a default and a schema entry:

```yaml
turn_input_defaults:
  my_signal: false           # or "" for string fields

turn_input_schema:
  my_signal:
    type: bool
    default: false
```

**Step 2 — Compute it at the end of `interpret_turn_input()` in `systools/runtime_adapters.py`**

Place the computation immediately before `return evidence`. Use only fields that already exist in `evidence` — no imports from `src/lumina/`, no hardcoded action names.

```python
# Compute my_signal from domain-owned evidence fields only.
evidence["my_signal"] = (
    evidence.get("some_domain_field") is True
    and evidence.get("step_count", 0) >= evidence.get("required_steps", 1)
)

return evidence
```

**Step 3 — Done. No changes to `src/lumina/`.**

The core engine reads the field by name via `turn_data.get("my_signal")`. If the field name is not yet in the engine contract field reference table above, open a PR to add it — that table is the only coupling point between domain packs and the core engine.

### Annotated reference: `problem_solved` in the education domain

```python
# At the end of interpret_turn_input() in
# domain-packs/education/systools/runtime_adapters.py

# A problem is fully solved when correctness is confirmed by substitution
# and the step-count minimum has been met. This flag is consumed by the
# core engine's problem-advancement gate and must not reference domain
# field names outside this adapter.
evidence["problem_solved"] = (
    evidence.get("correctness") == "correct"      # LLM or NLP confirmed correct
    and evidence.get("substitution_check") is True # algebra parser verified x=answer
    and evidence.get("step_count", 0) >= evidence.get("min_steps", 1)  # sufficient work shown
)
```

`min_steps` itself is a domain-owned field set by the problem generator (`problem_generator.py`) and carried through `current_problem` into the evidence defaults. The orchestrator's invariant check (`show_work_minimum`) uses `"step_count >= min_steps"` — the RHS is resolved as a field reference from evidence, not a hardcoded literal. This is also entirely within the domain pack.

---

## F. What NOT To Do

These are the anti-patterns that violate the domain-agnostic invariant. All three have been observed during development and should be caught in code review.

### ❌ Domain field names in `src/lumina/`

```python
# WRONG — in src/lumina/api/server.py
problem_solved = (
    correctness == "correct"
    and turn_data.get("substitution_check") is True   # ← education field
    and resolved_action not in {"request_more_steps"}  # ← education SO ID
)
```

`substitution_check` is an education field. `request_more_steps` is an education standing-order ID. Neither should appear in the core engine. The correct fix is to move the computation into the adapter (Phase B) and have the engine read only `turn_data.get("problem_solved")`.

### ❌ Calling domain-lib directly from the orchestrator

The orchestrator receives a `domain_lib_step_fn` lambda that wraps the domain's `domain_step` function. It calls that lambda — it does not import or call ZPD monitors, fluency trackers, or any other domain-lib component directly.

### ❌ Bypassing the adapter to write gate signals in the server

All engine contract fields must be populated by the domain pack's `interpret_turn_input`. Writing `turn_data["problem_solved"] = True` anywhere in `server.py` or in the orchestrator constitutes domain logic in the core and must be moved to the adapter.

---

## Reference: Education Domain Adapter Structure

```
domain-packs/education/
├── cfg/
│   └── runtime-config.yaml          ← declares defaults, schema, tool policies
├── domain-lib/
│   ├── zpd-monitor-spec-v1.md       ← passive: spec for ZPD state estimator
│   └── fatigue-estimation-spec-v1.md
├── systools/
│   ├── nlp_pre_interpreter.py       ← Phase A: answer match, frustration, hint, off-task
│   ├── zpd_monitor_v0_2.py          ← domain-lib implementation (called by runtime_adapters)
│   ├── fluency_monitor.py           ← domain-lib implementation (called by runtime_adapters)
│   ├── problem_generator.py         ← generates next task; sets min_steps
│   └── runtime_adapters.py          ← Phase A + Phase B synthesis; computes problem_solved
└── modules/algebra-level-1/
    └── tool-adapters/
        ├── algebra-parser-adapter-v1.yaml      ← active tool: called by policy
        └── substitution-checker-adapter-v1.yaml
```

---

## Reference: System Domain Adapter Structure

The system domain (`domain/sys/system-core/v1`) serves the special `system` role (root operators). It has no generative task: it is a read-only introspection surface for the Lumina OS runtime itself. This makes it a useful reference for the **minimal viable domain pack** pattern.

```
domain-packs/system/
├── cfg/
│   └── runtime-config.yaml          ← local_only: true; slm_weight_overrides;
│                                       adapters.tools; deterministic_templates
└── systools/
    ├── runtime_adapters.py           ← Phase A + Phase B; populates command_dispatch
    └── tool_adapters.py              ← direct tool adapters (no modules/ layer needed)
```

### `local_only: true`

The system domain sets `local_only: true` in its `runtime-config.yaml`. This flag is propagated by `load_runtime_context()` and causes `process_message()` to route the turn through the SLM rather than the LLM. **An external LLM is never called for system-domain turns** — this enforces a security boundary that prevents operational metadata (session IDs, physics hashes, escalation records) from being sent to third-party inference services.

If the SLM is unavailable, the turn resolves through the domain's `deterministic_templates` in the runtime config. The LLM is not used as a fallback.

```yaml
# domain-packs/system/cfg/runtime-config.yaml (excerpt)
local_only: true

deterministic_templates:
  system_command:    "Command received. Processing via system tools."
  system_status:     "System status: all subsystems nominal."
  system_diagnostic: "Diagnostic check complete. No anomalies detected."
  system_general:    "System acknowledged."
```

### No `modules/` layer

The system domain does not use the policy-driven tool adapter pattern. Its tool adapters are direct call adapters registered under `adapters.tools` and called from `interpret_turn_input` when `command_dispatch` carries a known operation name. This is appropriate for domains whose tools are pure read-only queries — no state is mutated, so policy gating adds no value.

### Action codes

The system domain's `system_domain_step` maps `query_type` evidence to six action codes:

| `query_type` | Action code |
|---|---|
| `admin_command` | `system_command` |
| `status_query` | `system_status` |
| `diagnostic` | `system_diagnostic` |
| `config_review` | `system_config_review` |
| `out_of_domain` | `out_of_domain` |
| anything else | `system_general` |

If `command_dispatch` is non-null in evidence (populated by `slm_parse_admin_command`), it overrides the `query_type` mapping and forces `system_command` regardless of the classified type.

