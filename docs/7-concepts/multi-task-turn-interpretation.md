---
version: 1.0.0
last_updated: 2025-07-19
status: Active
---
# Multi-Task Turn Interpretation

**Concept ID:** multi-task-turn-interpretation
**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-04-24
**Depends on:** [turn-interpretation-spec-v1](../../model-packs/assistant/domain-lib/reference/turn-interpretation-spec-v1.md), [nlp-semantic-router](nlp-semantic-router.md)

---

## The Problem

A user says: *"What's the weather like in Okinawa — I'm thinking of going in June."*

The single-task turn interpreter returns:

```json
{
  "intent_type": "general",
  "task_status": "n/a",
  "tool_call_requested": false,
  "off_task_ratio": 0.5
}
```

The `off_task_ratio: 0.5` is the system *feeling* tension between two intents but lacking vocabulary. The interpreter chose `general` because it couldn't pick between `weather` and `planning`. No tool was called. The user got a flat conversational response instead of grounded weather data and a trip plan.

The framework was observing intent collision but had no place to put the second intent.

---

## The Model: A Turn as a Task Graph

A turn produces not one piece of evidence but a **task graph**: an ordered set of subtasks with dependency edges.

```
turn input
    │
    ▼
┌──────────────────────────────┐
│   multi-task turn interpreter │
└──────────────────────────────┘
    │
    ▼
{
  "tasks": [
    { "task_id": 1, "intent": "weather", "blocked_by": [] },
    { "task_id": 2, "intent": "planning", "blocked_by": [1] }
  ]
}
    │
    ▼
framework graph walker
    ├─ dispatch task 1 → weather_lookup tool
    └─ dispatch task 2 → planning (needs task 1 result first)
    │
    ▼
LLM sees: weather data + planning intent → grounded, multi-part response
```

**The single-task turn is the degenerate case** — a one-node graph with no edges:

```
{ "tasks": [{ "task_id": 1, "intent": "weather", "blocked_by": [] }] }
```

All existing domain packs continue to work unchanged. The graph format is never produced unless the domain has registered a `multi_task_turn_interpreter` adapter.

---

## The pytest Analogy

The dependency structure maps directly to `pytest` ordering:

| pytest                              | Task Graph                         |
|-------------------------------------|-------------------------------------|
| `@pytest.mark.depends(on=["test_a"])` | `"blocked_by": [1]`               |
| Test `test_a` runs first             | Task 1 dispatched first (no deps)  |
| `test_b` runs after `test_a` passes  | Task 2 runs after task 1 completes |
| Skip on failure                      | `abandoned` cascades to dependents |

The framework computes a topological sort and dispatches tasks in dependency order. Cycles are invalid; the schema enforces acyclicity by construction (referenced task_ids must be lower-numbered than the referencing task, by convention).

---

## Worked Example: Okinawa

**User input:** *"What's the weather like in Okinawa — I'm thinking of going in June."*

**NLP pre-interpreter detects:** `intent_scores: {"weather": 2, "planning": 1}` — two non-zero scores. Multi-task path fires.

**Multi-task interpreter emits:**

```json
{
  "tasks": [
    {
      "task_id": 1,
      "intent": "weather",
      "status": "pending",
      "blocked_by": [],
      "turn_data": {
        "intent_type": "weather",
        "task_status": "open",
        "tool_call_requested": true,
        "location": "Okinawa",
        "forecast_days": 3,
        "off_task_ratio": 0.0,
        "satisfaction_signal": "unknown"
      }
    },
    {
      "task_id": 2,
      "intent": "planning",
      "status": "pending",
      "blocked_by": [1],
      "turn_data": {
        "intent_type": "planning",
        "task_status": "open",
        "tool_call_requested": false,
        "off_task_ratio": 0.0,
        "satisfaction_signal": "unknown"
      }
    }
  ]
}
```

**Framework graph walker:**

1. Task 1 (`weather`, no deps): `orch.process_turn(...)` → `weather_lookup` action → `apply_tool_call_policy` fires `weather_lookup_tool("Okinawa")` → returns `{temp_c: 28, condition: "Sunny", ...}`
2. Task 2 (`planning`, blocked by 1): blocked — deferred to `pending_tasks` in orch state for next turn.
3. LLM payload assembled: `tool_results = [weather_data]`, prompt_contract from primary task.

**LLM response:** *"Okinawa looks great in June — temperatures around 28°C and mostly sunny. It's peak rainy season early June so aim for mid-to-late June. Want me to put together an itinerary?"*

Task 2 surfaces on the next turn with the weather result available as context.

---

## `off_task_ratio` as a First-Class Signal

In the single-task model, `off_task_ratio: 0.5` was noise. In the multi-task model it is the **primary heuristic trigger**:

- `off_task_ratio: 0.0` + NLP detects one intent → single-task path (normal)
- `off_task_ratio > 0.3` OR NLP detects ≥ 2 intents → multi-task path (if domain opted in)
- `off_task_ratio: 1.0` → message is entirely off-topic; return to single-task general path

The NLP pre-interpreter runs deterministically (no LLM call) before turn interpretation, returning `intent_scores` (a dict of `{intent: keyword_hit_count}` for each known intent). If two or more intents have non-zero scores and the domain has registered a `multi_task_turn_interpreter` adapter, the framework routes to the multi-task interpreter.

---

## Subtask Failure Semantics

When a subtask enters `abandoned` status:

1. All tasks in its `blocked_by` chain also transition to `abandoned`.
2. Completed tasks before the failure are retained — partial results reach the LLM.
3. The user sees a grounded response for the completed tasks plus a note that the failed task could not complete.

This mirrors `pytest --no-fail-fast` with `depends` — failed tests abort their dependents but the rest of the suite continues.

---

## Graph Persistence: `pending_tasks` Queue

Tasks with non-empty `blocked_by` lists are not immediately runnable. The framework stores them in `orch.state["pending_tasks"]` — a list of `{task_id, intent, turn_data}` dicts. They survive the turn and are available to the LLM as context on the next message.

When the user continues the conversation (e.g. *"Yes, let's plan the trip"*), the orchestrator state carries the pending tasks forward, and the next turn can complete the planning leg.

The existing `pending_tool_call` / `pending_tool_intent` singular state keys remain supported as a backward-compat shim. They are wrapped into a one-element `pending_tasks` list when encountered.

---

## Domain Pack Opt-In

A domain pack opts into multi-task interpretation by:

1. Registering a `multi_task_turn_interpreter` adapter in `runtime-config.yaml`:

   ```yaml
   adapters:
     multi_task_turn_interpreter:
       module_path: model-packs/assistant/controllers/runtime_adapters.py
       callable: interpret_multi_task_input
   ```

2. Providing a `multi_task_interpretation_prompt_path` in the `runtime:` section:

   ```yaml
   runtime:
     multi_task_interpretation_prompt_path: model-packs/assistant/domain-lib/reference/multi-task-turn-interpreter-spec-v1.md
   ```

When neither is present, the single-task path runs unchanged. The framework never assumes multi-task capability.

---

## Schema Reference

Task graph output conforms to [turn-task-graph-schema-v1.json](../../standards/turn-task-graph-schema-v1.json).

Per-task `turn_data` fields conform to the domain's `turn_input_schema` — identical semantics as single-task turn_data.

---

## Related Concepts

- [nlp-semantic-router.md](nlp-semantic-router.md) — the NLP pre-interpreter that triggers multi-task detection
- [prompt-packet-assembly.md](prompt-packet-assembly.md) — how aggregated tool results feed the LLM payload
- [context-is-not-conversation.md](context-is-not-conversation.md) — why task graph state is not the same as conversation state
- [dsa-framework.md](dsa-framework.md) — the orchestration framework that dispatches each subtask
