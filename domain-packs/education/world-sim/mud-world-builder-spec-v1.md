# MUD World Builder Specification — Education Domain (V1)

> **Domain scope:** This specification covers the MUD World Builder extension to the education domain's world-sim persona layer. It is an education-domain-only feature; no other domain pack is affected.

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-16

---

## Overview

The **MUD World Builder** is an advanced dynamic persona layer for the education domain. At session start, it generates 8 narrative constants — a **World State** — from the student's interest profile and locks them into the session's `LearningState`. Every turn of the session draws on this locked state to narrate algebra problems as steps in a text-based adventure ("MUD" — Multi-User Dungeon style), making the math feel physically grounded in a world the student is already curious about.

> **The World State is the skin. Domain Physics is the skeleton. The skeleton never changes because the skin does.**

The MUD World Builder supplements — does not replace — the existing `world_sim_theme` selection (see [`world-sim-spec-v1.md`](world-sim-spec-v1.md)). Both systems are active simultaneously. `world_sim_theme` continues to control broad session framing (`task_framing`, `artifact_framing`, `exit_phrase`). The MUD World State provides the richer 8-field narrative constants that pin down the specific characters, setting, and in-world physics of the session.

---

## The World State — 8 Field Structure

Once generated, the World State is a locked JSON object carried on `LearningState.mud_world_state` for the entire session. The schema is defined in [`schemas/mud-world-state-schema.json`](../schemas/mud-world-state-schema.json).

| Field | Purpose | Example (Dark Fantasy) |
|---|---|---|
| `zone` | The physical in-world setting | `"The Sunken Catacombs of Aethelgard"` |
| `protagonist` | The student's in-world role | `"Novice Spellweaver"` |
| `antagonist` | The boss character — creates narrative pressure | `"Xylar the Undying (arrogant Lich)"` |
| `guide_npc` | The hint character — all hints are spoken in their voice | `"Barnaby (sarcastic enchanted grimoire)"` |
| `macguffin` | The objective — motivates every equation | `"The Crown of Dawn"` |
| `variable_skin` | What the unknown variable(s) represent in this world | `"Unstable Mana Crystals"` |
| `obstacle_theme` | How equations are physically represented | `"Magical Counter-Weight Scales and Runic Doors"` |
| `failure_state` | Exact narrative consequence on invariant violation | `"Trap triggered! A poison dart strikes you. Lose 10 HP."` |

### Why each field matters

**`zone`** locks the setting so the AI never hallucinates inconsistent environments. A sci-fi equation-terminal is not replaced by a medieval rune-door halfway through the module.

**`protagonist` / `antagonist`** give the student and the boss a stable identity. The antagonist creates narrative pressure ("*You call that algebra, Phantom?*") without demeaning the student personally.

**`guide_npc`** makes hint delivery feel organic. Every hint is narrated in the NPC's distinct voice characteristic rather than as plain curriculum text.

**`macguffin`** provides the narrative *why* behind each equation. The student is not "doing math problem 7" — they are one step closer to escaping the station, cracking the vault, or finding the antidote.

**`variable_skin`** is the most critical field for domain-physics coherence. The AI must never refer to the algebraic unknown by its bare letter (e.g. "x") — it must use the variable skin. The underlying algebra check is identical; only the label changes.

**`obstacle_theme`** determines how the equation is physically described. "The laser grid has a firewall value of 17" and "The scales must balance at 17" both represent `3x + 5 = 17` — the domain-physics check is the same.

**`failure_state`** ensures that invariant violations feel like game mechanics rather than test red-marks. The exact string in this field is used **verbatim** by the orchestrator persona — it is not paraphrased.

---

## Template Library

World States are generated from the template library at [`mud-world-templates.yaml`](mud-world-templates.yaml). Each template defines all 8 fields plus a `preference_keywords` list that is matched against the student's interest profile.

The library ships with 6 named templates and one fallback:

| Template ID | Target interests |
|---|---|
| `dark_fantasy_dungeon` | fantasy, D&D, Elden Ring, magic, dragons, RPG |
| `zombie_survival` | zombies, The Last of Us, Resident Evil, survival, horror |
| `cyber_heist` | cyberpunk, hacking, spy, heist, stealth, tech |
| `space_mission` | space, rockets, astronaut, NASA, sci-fi, astronomy |
| `nature_expedition` | nature, animals, outdoors, wildlife, ecology |
| `sports_arena` | sport, soccer, basketball, gaming, esports |
| `general_math` | *(empty — catch-all fallback)* |

New templates can be added by a Domain Authority by appending entries to `mud-world-templates.yaml`. No code changes are required.

---

## Template Selection Algorithm

`generate_mud_world(entity_profile, mud_world_cfg)` in `systools/runtime_adapters.py`:

1. If `mud_world_cfg` is absent or `enabled: false` → return `{}`.
2. Load templates from `mud_world_cfg["templates"]` (pre-loaded list from `mud-world-templates.yaml`).
3. Collect `preferences.interests` and `preferences.likes` (both, lowercased; `interests` is canonical, `likes` is the legacy alias). Merge into a single set.
4. Collect `preferences.dislikes` (lowercased).
5. Iterate templates in order:
   a. Skip if `preference_keywords` has any overlap with dislikes (dislike always vetoes).
   b. Return first template whose `preference_keywords` overlaps with interests/likes (strip `preference_keywords` from return; keep all 8 narrative fields + `template_id`).
6. Fallback: return the first template with an empty `preference_keywords` list (`general_math`).
7. If no fallback exists, return `{}`.

**Determinism guarantee:** Given the same profile and the same template list, `generate_mud_world()` always returns the same World State. The session-open `CommitmentRecord` records the `template_id` for audit traceability.

---

## Session Lock-In Contract

The World State is generated **once** in `build_initial_learning_state()` and stored on `LearningState.mud_world_state`. It does not change within a session, even if the student sends a message that mentions a different topic. `domain_step()` explicitly preserves `mud_world_state` across the ZPD monitor's state replacement step.

The locked state is injected into the LLM context on every turn via a `[MUD World Active]` hint block in `interpret_turn_input()`, providing all 8 fields to the orchestrator. This ensures the Game Master never "loses the plot."

---

## Domain-Physics Invariant Contract

The World State changes the narrative surface only. Every domain-physics invariant check is identical in-world and out-of-world:

| Invariant | In-world violation narrative | Underlying check |
|---|---|---|
| `equivalence_preserved` | Uses `failure_state` verbatim | `equivalence_preserved == True` |
| `no_illegal_operations` | Uses `failure_state` verbatim | `illegal_operations == []` |
| `solution_verifies` | Uses `failure_state` verbatim | `substitution_check == True` |
| `show_work_minimum` | Uses `failure_state` verbatim | `step_count >= min_steps` |

The `failure_state` is a single string representing the generic consequence for *any* invariant violation in this world (e.g., "Lose 10 HP"). The orchestrator may prefix with the specific violation rule ("Unbalanced equation detected!") before appending the failure_state.

---

## Persona Execution Rules

These rules are enforced by the domain system prompt in [`../prompts/domain-system-override.md`](../prompts/domain-system-override.md):

1. **Variable skin** — Never use the bare variable letter. Refer to the unknown using `variable_skin`. The word "x" (or "y", etc.) must appear only inside equation display; narrative language always uses the skin.
2. **Invariant consequence** — When an invariant is violated, speak the `failure_state` verbatim before providing pedagogical guidance.
3. **Hint voice** — All hints are delivered in the voice of `guide_npc`. Use their name and the voice characteristic described in the template.
4. **Antagonist taunts** — The antagonist may deliver one brief taunt (≤ 1 sentence) on an incorrect step. Rules:
   - Target the in-world *action*, not the student's ability ("*The scale tips wildly, Spellweaver!*" — not "*You're bad at math*").
   - Age-appropriate; never demeaning, never personal.
   - Taunts are optional and should not appear more than once per turn.
5. **MacGuffin motivation** — Weave the `macguffin` into the introduction of each new task (e.g., "One step closer to the Crown of Dawn — but first, Barnaby says this scale must balance…").
6. **Obstacle theme narration** — Describe the equation in terms of the `obstacle_theme` when presenting it. The narrative should describe the physical state of the obstacle *before* asking the student to engage.

---

## Consent and Scope

The MUD World Builder operates within the same magic circle consent established by [`magic-circle-consent-v1.md`](magic-circle-consent-v1.md). No additional consent step is required. The student's profile interests are used solely for framing (Principle 6 — immersion is non-grading; see `magic-circle-consent-v1.md`).

The world builder does not introduce any new data collection. The `template_id` is recorded in the session-open CommitmentRecord for audit purposes; narrative content is ephemeral (not stored in the System Logs).

---

## Configuration Reference

In `runtime-config.yaml` under `world_sim`:

```yaml
world_sim:
  enabled: true
  default_theme: general_math
  mud_world_builder:
    enabled: true
    # templates: <list> — populated at runtime by loading mud-world-templates.yaml
```

The templates are loaded from `mud-world-templates.yaml` by the server/orchestrator at startup and passed into `build_initial_learning_state()` via the `mud_world_cfg` parameter.

---

## Extension Points

**Adding templates:** Append a new entry to `mud-world-templates.yaml` with a unique `id`, relevant `preference_keywords`, and the 8 narrative fields. No code changes required. Templates added by a Domain Authority are governed by the same RBAC rules as domain pack modifications.

**Localisation / translation:** All 8 narrative fields are plain strings. A translated variant of the template library can be added as `mud-world-templates-{locale}.yaml` and selected via a `locale` field in the student profile.

**LLM-generated worlds (future):** For student profiles with no matching template, a future extension may invoke the LLM to generate a custom World State conforming to `mud-world-state-schema.json`. This must be implemented as a deterministic-then-LLM cascade: try the template library first; only invoke the LLM if the library has no match and `allow_generated_worlds: true` is set in the configuration. Generated worlds would require validation against the schema before use.

---

## References

- [`world-sim-spec-v1.md`](world-sim-spec-v1.md) — parent world-sim specification; persona model and invariant contract
- [`magic-circle-consent-v1.md`](magic-circle-consent-v1.md) — consent activation gate
- [`artifact-and-mastery-spec-v1.md`](artifact-and-mastery-spec-v1.md) — artifact award and boss challenge rules (unaffected by MUD framing)
- [`mud-world-templates.yaml`](mud-world-templates.yaml) — the template library
- [`../schemas/mud-world-state-schema.json`](../schemas/mud-world-state-schema.json) — JSON Schema for the World State object
- [`../prompts/domain-system-override.md`](../prompts/domain-system-override.md) — persona execution rules for the orchestrator
- [`../../../docs/7-concepts/world-sim-persona-pattern.md`](../../../docs/7-concepts/world-sim-persona-pattern.md) — generalized pattern documentation
