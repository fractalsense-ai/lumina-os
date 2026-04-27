---
version: 1.0.0
last_updated: 2026-04-19
---

# MUD Dynamic World Builder

The **MUD World Builder** is the education domain's advanced dynamic persona
pattern, implemented on top of the standard theme selection layer described in
[`world-sim-persona-pattern(7)`](../../../../docs/7-concepts/world-sim-persona-pattern.md).

Where the standard Dynamic Persona selects one of a small set of broad themes
(e.g., `space_exploration`, `sports_and_games`), the MUD World Builder generates
a **World State** — 8 narrative constants that stay identical for the entire
session, eliminating narrative drift completely:

| Field | Role |
|---|---|
| `zone` | The session setting; prevents hallucinated environment changes |
| `protagonist` | The student's in-world role |
| `antagonist` | The boss who creates pressure |
| `guide_npc` | The hint character, with a distinct voice |
| `macguffin` | The objective that motivates every equation |
| `variable_skin` | What the algebraic unknown *is* in this world |
| `obstacle_theme` | How equations are physically represented |
| `failure_state` | Exact narrative consequence on any invariant violation |

The same $3x + 5 = 17$ algebra check spawns different narration in each
world — but the `equivalence_preserved` invariant fires identically regardless:

- **Dark Fantasy:** *"The counter-weight scale violently tips! Trap triggered! A poison dart strikes you. Lose 10 HP."*
- **Zombie Survival:** *"The elevator sparks! Too much noise! Horde Proximity +15%."*
- **Cyber-Heist:** *"ACCESS DENIED. Security tripped! Alert Level rises."*

## Selection Algorithm

`generate_mud_world(entity_profile, mud_world_cfg)` in `controllers/runtime_adapters.py`:

1. Collect `preferences.interests` and `preferences.likes` (both; merged into one set).
2. Collect `preferences.dislikes`.
3. Iterate the template library (in `mud-world-templates.yaml`).
4. Skip any template whose `preference_keywords` overlaps with dislikes.
5. Return first template whose `preference_keywords` overlaps with interests/likes.
6. Fallback: return the first zero-keyword template (`general_math`).

The generated World State is stored as `state.mud_world_state` at session start
and injected into every turn's context as a `[MUD World Active]` hint block. The
session-open `CommitmentRecord` captures the `template_id` for audit traceability.

## Relationship to Standard Theme Selection

Both systems are active simultaneously. They are complementary, not competing:

- `world_sim_theme` → controls `task_framing`, `artifact_framing`, `exit_phrase` (broad UX labels)
- `mud_world_state` → controls `zone`, `protagonist`, `antagonist`, `guide_npc`, `macguffin`, `variable_skin`, `obstacle_theme`, `failure_state` (session narrative constants)

## See also

- [`world-sim-persona-pattern(7)`](../../../../docs/7-concepts/world-sim-persona-pattern.md) — framework-level persona pattern
- [`model-packs/education/world-sim/mud-world-builder-spec-v1.md`](../../world-sim/mud-world-builder-spec-v1.md) — full MUD builder specification
- [`model-packs/education/world-sim/mud-world-templates.yaml`](../../world-sim/mud-world-templates.yaml) — template library
