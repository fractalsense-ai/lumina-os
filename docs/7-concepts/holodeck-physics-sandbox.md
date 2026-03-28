---
version: 1.0.0
last_updated: 2026-03-28
---

# Concept — Physics Sandbox (Holodeck)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-28  

---

## NAME

holodeck-physics-sandbox — a synthetic test environment for previewing proposed domain-physics changes through the full D.S.A. pipeline before they enter the live system.

> **Internal project name:** *Holodeck.* This name appears in the route path (`/api/holodeck/simulate`), in ephemeral session IDs (`holodeck-{uuid}`), and throughout the test suite. The terms are used interchangeably in this document.

## SYNOPSIS

The Physics Sandbox lets domain authorities and root users run a test message through the complete Lumina pipeline — NLP normalization, invariant checking, tool dispatch, LLM response — using *proposed* domain physics without touching the live system. The simulation is fully ephemeral: the sandbox session is created and torn down within the request, the live domain physics registry is never mutated, and no session state persists after the response.

Two input modes are supported:

- **`physics_override`** — supply an inline dict of proposed physics changes directly in the request body. Used for rapid exploration during physics authoring.
- **`staged_id`** — reference an in-flight HITL staged command from the admin pipeline. Used to preview a proposed change before a root user approves or rejects it.

The response contains the full simulation result alongside a physics diff, live-vs-sandbox hashes, and a `holodeck` evidence block in the structured content.

---

## ACCESS CONTROL

| Role | Access |
|------|--------|
| `root` | Full access — can simulate any domain |
| `domain_authority` | Scoped access — can only simulate domains in their `governed_modules` list |
| `user` and all other roles | 403 Forbidden |

Role checks are enforced at the route level before any processing occurs.

---

## INPUT MODES

### `physics_override` — Inline Changes

Supply a partial or complete physics dict directly. The sandbox merges this over a deep copy of the current live physics using shallow key assignment:

```json
{
  "domain_id": "_default",
  "message": "solve x + 1 = 3",
  "physics_override": {
    "invariants": [
      {
        "id": "custom_sandbox_invariant",
        "description": "Proposed new invariant",
        "severity": "warning",
        "check": "sandbox_flag"
      }
    ]
  }
}
```

Only the specified keys are replaced. Keys not present in `physics_override` retain their live values.

### `staged_id` — Admin Pipeline Reference

Reference the ID of a pending staged command from either:

1. **In-memory admin staged commands** — created via `POST /api/admin/command` and held in `_STAGED_COMMANDS` while awaiting HITL resolution.
2. **On-disk `StagingService` envelopes** — domain-physics files staged via the ingestion/staging pipeline with `template_id: domain-physics`.

```json
{
  "domain_id": "_default",
  "message": "solve x + 1 = 3",
  "staged_id": "your-staged-command-id"
}
```

The staged command must be:
- `operation: update_domain_physics` (admin pipeline) or `template_id: domain-physics` (staging pipeline)
- Not yet resolved/approved — already-resolved staged commands return 409

### Validation

Exactly one of `staged_id` or `physics_override` must be provided. Both together or neither both return 422.

---

## SIMULATION FLOW

```
Request (physics_override or staged_id)
    │
    ├── Auth + role gate
    │
    ├── Resolve sandbox physics
    │     deepcopy(live_physics)
    │     + merge overrides/staged updates
    │
    ├── Compute hashes + diff
    │     live_physics_hash = sha256(live_physics)
    │     sandbox_physics_hash = sha256(sandbox_physics)
    │     physics_diff = {added, removed, changed}
    │
    ├── Create ephemeral session: holodeck-{uuid}
    │
    ├── process_message(
    │       session_id=holodeck-{uuid},
    │       message=req.message,
    │       turn_data_override=req.turn_data_override,
    │       holodeck=True,
    │       physics_override=sandbox_physics
    │   )
    │     ── runs full pipeline: NLP → invariant check → tools → LLM
    │
    └── (finally) remove holodeck-{uuid} from _session_containers
```

The `holodeck=True` flag tells `process_message` to use the provided `sandbox_physics` instead of loading physics from the registry. The live registry is never written.

---

## RESPONSE STRUCTURE

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | The ephemeral session ID (`holodeck-{uuid}`). Always starts with `holodeck-`. |
| `response` | string | The LLM (or deterministic) text response. |
| `action` | string | The resolved action from the D.S.A. orchestrator. |
| `prompt_type` | string | The prompt contract type that was resolved. |
| `escalated` | bool | Whether an escalation was triggered during the simulation. |
| `tool_results` | object \| null | Results from tool adapter calls, if any. |
| `domain_id` | string | The resolved domain ID that was simulated. |
| `structured_content` | object | Structured output from the domain adapter. Contains a `holodeck` evidence block (see below). |
| `sandbox_physics` | object | The full physics dict that was used for the simulation. |
| `physics_diff` | object | Shallow diff between live and sandbox physics: `{added, removed, changed}`. |
| `live_physics_hash` | string | SHA-256 of the live physics (canonical JSON). |
| `sandbox_physics_hash` | string | SHA-256 of the sandbox physics (canonical JSON). |
| `staged_id` | string \| null | Echo of the `staged_id` from the request, if provided. |

### The `holodeck` Evidence Block

When the domain adapter produces structured content, it includes a `holodeck` sub-object with simulation-specific diagnostic fields:

```json
{
  "structured_content": {
    "holodeck": {
      "state_snapshot": { ... },     // session state at simulation time
      "inspection_result": { ... },  // tool adapter verification output
      "invariant_checks": [ ... ]    // which invariants were evaluated and their outcomes
    }
  }
}
```

This block is the primary mechanism for inspecting how proposed physics behaves against a test message — which invariants fire, which tool adapters activate, what evidence was computed.

---

## THE NO-POLLUTION GUARANTEE

Three mechanisms ensure the sandbox cannot affect the live system:

1. **Deep copy** — `sandbox_physics = copy.deepcopy(live_physics)` before any merge. No reference to live physics objects survives into the simulation.
2. **Registry never written** — `DOMAIN_REGISTRY.get_runtime_context()` is read-only during simulation. The `holodeck=True` flag routes physics through `process_message`'s override path, bypassing the registry entirely.
3. **`finally` cleanup** — the ephemeral session container is unconditionally removed from `_session_containers` after the request completes, whether `process_message` succeeds or raises. No sandbox session state leaks into subsequent requests.

---

## TYPICAL WORKFLOW

The physics sandbox fits into the domain authority workflow at the preview step:

```
1. A teacher (user) notices the domain physics needs adjustment.
   └─ They issue a natural-language change request to the system.

2. The system interprets the request, drafts a proposed physics change,
   and submits it as a HITL staged command via POST /api/admin/command.

3. The domain authority (or root) receives the staged command ID.
   └─ They call POST /api/holodeck/simulate with staged_id to preview
      how the proposed change would behave against a representative message.

4. The holodeck response shows:
   - What the LLM would have responded under the new physics
   - Which invariants fired / changed behaviour
   - The exact diff between live and proposed physics
   - The SHA-256 hashes for audit trail

5. If satisfied, the authority approves the staged command via
   POST /api/admin/command/resolve → CommitmentRecord written to System Log.
   If not, they reject or request revision.
```

---

## OPERATING NOTES

- **No System Log record is written** for holodeck simulations. The `holodeck=True` flag suppresses the log commit requirement (`@requires_log_commit` semantics do not apply to the sandbox route). The simulation is diagnostic, not operational.
- **The black-box trigger system may fire** during simulation if, for example, the sandbox physics trigger an escalation. The resulting blackbox file will have a session ID starting with `holodeck-` — this is expected and identifiable.
- **`turn_data_override`** allows the caller to inject pre-computed turn evidence (e.g., `substitution_check: true`, `method_recognized: true`) to test specific invariant paths without depending on LLM-extracted fields.
- **`deterministic_response`** bypasses the LLM and uses the domain-pack's deterministic response renderer. Useful for rapid physics testing where the response text is not the focus.

---

## SOURCE FILES

| File | Role |
|------|------|
| `src/lumina/api/routes/holodeck.py` | Route handler, physics diff, staged-command resolution |
| `src/lumina/api/models.py` | `HolodeckSimulateRequest`, `HolodeckSimulateResponse` Pydantic models |
| `src/lumina/api/processing.py` | `process_message()` — the full pipeline; respects `holodeck=True` flag |
| `tests/test_holodeck_sandbox.py` | Feature I test suite |

---

## SEE ALSO

- [`prompt-packet-assembly(7)`](prompt-packet-assembly.md) — the pipeline that holodeck drives end-to-end
- [`domain-pack-anatomy(7)`](domain-pack-anatomy.md) — domain physics structure and invariant authoring
- [`state-change-commit-policy(7)`](state-change-commit-policy.md) — why holodeck does not write a log record
- [`execution-route-compilation(7)`](execution-route-compilation.md) — compiled routes that are rebuilt when physics changes are committed
- [`telemetry-and-blackbox(7)`](telemetry-and-blackbox.md) — the black-box snapshot that may be triggered during simulation
