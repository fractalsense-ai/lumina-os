# Governance Turn Interpretation Specification — Education Domain

**Spec ID:** governance-turn-interpretation-spec-v1  
**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-04-05  
**Domain:** education (governance roles)  
**Conformance:** Required — all education governance turn interpretation must emit this schema.

---

## Purpose

This Technical Manual specifies the turn interpretation schema for
**education governance roles**: Domain Authority, Teacher, Teaching
Assistant, and Guardian. These roles do NOT produce learning evidence
(ZPD, correctness, step_count, fluency) — they produce governance
evidence (query_type, command_dispatch, urgency, target_component).

## Pipeline Position

```
Governance operator message
  │
  ├─→ NLP Pre-Interpreter  (deterministic, <1ms)
  │      └─→ _nlp_anchors: admin_command detection, keyword extraction
  │
  ├─→ SLM Turn Interpreter  (Ollama, governance_adapters.interpret_turn_input)
  │      └─→ governance-shaped evidence JSON
  │
  └─→ Orchestrator  (PPA action resolution from governance evidence)
         └─→ admin command dispatch or governance response
```

**Key constraint:** Governance turns are SLM-only (`local_only: true`
per-module). The LLM (OpenAI) is NEVER invoked for governance turn
classification. This is enforced by the per-module `local_only` flag
in `runtime-config.yaml`.

## Output Schema

All governance turn interpreters MUST emit exactly these fields:

```json
{
  "query_type": "<classification>",
  "command_dispatch": "<operation_name or null>",
  "target_component": "<subsystem or null>",
  "urgency": "<level>",
  "response_latency_sec": "<float>",
  "off_task_ratio": "<float 0..1>"
}
```

### Field Definitions

| Field | Type | Description |
|---|---|---|
| `query_type` | enum | Primary intent classification (see taxonomy below) |
| `command_dispatch` | string\|null | Admin operation name when query_type is `admin_command` |
| `target_component` | string\|null | The governance subsystem being addressed |
| `urgency` | enum | `routine`, `elevated`, `critical` |
| `response_latency_sec` | float | Time to operator response, default 5.0 |
| `off_task_ratio` | float | 0.0 = on-task governance, 1.0 = entirely off-topic |

### query_type Taxonomy

| Value | When to use |
|---|---|
| `admin_command` | Operator requests an action (mutating or read-only admin) — e.g. "list users", "invite student", "resolve escalation" |
| `status_check` | Operator asks about current state — e.g. "how many active students", "module health" |
| `module_management` | Module assignments, activation, configuration — e.g. "what modules are available" |
| `escalation_review` | Reviewing or acting on escalation packets — e.g. "show open escalations" |
| `physics_edit` | Inspecting or modifying domain physics — e.g. "what are the invariants" |
| `general` | Governance-related but doesn't fit above categories — greetings, help, meta-questions |

### target_component Values

Use: `"physics"`, `"roles"`, `"escalations"`, `"modules"`, `"progress"`,
`"ingestion"`, `"daemon"`, `"commands"`, `"domains"`, or `null` if unclear.

## Contrast with Learning Turn Interpretation

| Aspect | Student (Learning) | Governance |
|---|---|---|
| Evidence fields | correctness, step_count, problem_solved, zpd_delta, fluency_streak | query_type, command_dispatch, urgency, target_component |
| Interpreter | runtime_adapters.interpret_turn_input | governance_adapters.interpret_turn_input |
| Model used | LLM (OpenAI) | SLM (Ollama) — local_only |
| NLP anchors | equation parsing, math pattern detection | admin command detection, keyword extraction |
| Physics context | ZPD invariants, fluency gates | governance standing orders, escalation triggers |

## Role-Specific Guidance

### Domain Authority
- Has full governance scope across governed modules
- Admin commands include: invite_user, assign_domain_role, resolve_escalation,
  update_domain_physics, list_users, list_escalations, etc.
- Can modify physics, manage roles, and resolve escalations

### Teacher
- Scoped to classroom management within assigned modules
- Primary operations: list_users (students in module), review progress,
  resolve low-severity escalations, request_module_assignment
- Cannot modify domain physics or system-level roles

### Teaching Assistant
- Supports teacher with student monitoring
- Primary operations: list_users, module_status, explain_reasoning
- Cannot resolve escalations or modify roles

### Guardian
- Read-only access to student progress
- Primary operations: module_status (for their student), explain_reasoning
- Cannot modify any governance state

## Related Files

- `model-packs/education/controllers/governance_adapters.py` — interpreter implementation
- `model-packs/education/prompts/governance-turn-interpretation-spec-v1.md` — SLM prompt text
- `model-packs/education/cfg/admin-operations.yaml` — operation definitions
- `model-packs/education/cfg/runtime-config.yaml` — module routing and local_only flags
