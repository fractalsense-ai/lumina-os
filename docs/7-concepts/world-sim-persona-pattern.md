---
version: 1.0.0
last_updated: 2026-03-20
---

# World-Sim as Domain Persona — Pattern Reference

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-13

---

## Overview

Every domain pack can optionally project a **persona** — a narrative identity the AI adopts for the duration of a session. The world simulation (world-sim) is the mechanism that implements this persona. It is a cosmetic framing layer: the narrative changes how domain content is *presented*, never what it *is*.

This document defines the pattern so that any domain pack can adopt it. The education domain is the reference implementation.

---

## The Three-File Composition

A complete world-sim persona is defined by three spec files, owned by the domain:

| File | Role in the Persona |
|---|---|
| `world-sim-spec-v1.md` | **Persona parameters** — theme, setting description, in-world labels for tasks and artifacts, exit phrase, theme selection rules |
| `magic-circle-consent-v1.md` | **Activation gate** — the persona does not turn on until the participant gives informed consent. The consent process is the "magic circle" that marks the boundary between real interaction and immersive framing. |
| `artifact-and-mastery-spec-v1.md` | **Reward surface** — earned milestones (artifacts) may be presented with in-world names. Only the display name is part of the persona; the functional definition (mastery threshold, skills required) is invariant. |

All three files live under `domain-packs/<domain>/world-sim/`.

> **Key principle:** The persona is the skin. The domain physics is the skeleton. The skeleton never changes because the skin does.

---

## Static vs. Dynamic Persona

### Static Persona

The domain pack declares a single fixed theme in `runtime-config.yaml`. Every session uses the same narrative context regardless of who the participant is.

```yaml
world_sim:
  enabled: true
  default_theme: space_exploration
  themes:
    space_exploration:
      setting_description: "You are the mission mathematician aboard the Helios research vessel."
      artifact_framing: "mission_badge"
      task_framing: "mission_briefing"
      exit_phrase: "end mission"
      preference_keywords: []
```

This is the simplest option. Use it when a domain has a single well-defined narrative context.

### Dynamic Persona

The domain pack declares multiple themes and uses the entity's preference profile to select one at session start. The selection runs once in `build_initial_learning_state` and is stored on the domain state object for the session's duration.

**Selection rules (enforced by `select_world_sim_theme`):**
1. Collect the entity's `preferences.interests` list (and `preferences.likes` as a legacy alias; both are checked).
2. Find the first theme whose `preference_keywords` overlaps with the interests list.
3. Skip any theme whose `preference_keywords` overlaps with the entity's `dislikes` list (dislike always wins over like).
4. Fall back to `default_theme` if no match is found.
5. Return `{}` if `world_sim.enabled` is `false`.

The selected theme config dict is stored as `state.world_sim_theme` and forwarded to `interpret_turn_input` on every turn as a hint block:

```
[World-Sim Active] Setting: <setting_description>.
Use in-world framing ('<task_framing>') for task labels.
Artifact framing: '<artifact_framing>'.
```

Module-level overrides are declared in `domain-physics.yaml` under `world_sim_override` and allow a specific module to restrict available themes or change the default within that module's scope.

---

## Engine Contract Invariant

The world-sim persona never alters what the core engine enforces. The following are preserved regardless of narrative framing:

- Invariant checks run identically in-world and out-of-world
- Mastery thresholds and proficiency calculations are unchanged
- Consent, escalation, and exit clause mechanics are unchanged
- The System Logs records functional outcomes, not narrative content
- Assessment is based on verifiable domain outcomes (see `domain-adapter-pattern.md`), never on behavioral inference or narrative engagement

The AI may use in-world language to communicate constraint violations. The underlying check is identical:

> *"Your equation must stay balanced — the mission computer won't accept unbalanced equations"* enforces `equivalence_preserved` exactly as much as *"Your equation is unbalanced"*.

---

## How Other Domains Adopt the Pattern

Any domain pack may add a `world-sim/` folder. The three-file pattern is the template:

| Domain | Example Setting | Artifact Framing | Task Framing |
|---|---|---|---|
| **Education** (ref impl) | `"You are the mission mathematician aboard the Helios research vessel."` | `mission_badge` | `mission_briefing` |
| **Agriculture** (example) | `"You are managing the Thornfield research farm."` | `harvest_record` | `field_task` |
| **Medical** (example) | `"You are on duty at the forward field hospital."` | `clinical_competency_record` | `patient_case` |

The consent spec (`magic-circle-consent-v1.md`) must be adapted for each domain using domain-appropriate participant and authority terminology — the education version refers to "student," "parent/guardian," and "teacher." A medical version would use "patient," "healthcare proxy," and "supervising clinician."

The domain does not need to be dynamic to adopt world-sim. A static fixed theme is a fully valid implementation.

---

## Configuration Reference

### `runtime-config.yaml` — Domain-wide defaults

```yaml
world_sim:
  enabled: true                     # set to false to disable entirely
  default_theme: general            # used when no preference match is found
  themes:
    <theme_id>:
      setting_description: "..."    # injected as the session context description
      artifact_framing: "..."       # replaces "certificate" / "badge" labels
      task_framing: "..."           # replaces "problem" / "task" labels
      exit_phrase: "..."            # in-world equivalent of "exit session"
      preference_keywords: [...]    # matched against entity profile preferences.likes
```

### `domain-physics.yaml` — Optional per-module override

```yaml
world_sim_override:
  default_theme: space_exploration      # override the domain-wide default for this module
  available_themes:                     # restrict to a subset of domain-wide themes
    - space_exploration
    - general_math
```

If `world_sim_override` is absent, the module inherits the domain-wide `world_sim` config from `runtime-config.yaml`.

---

## Implementation Checklist (for new domain packs)

- [ ] Create `domain-packs/<domain>/world-sim/` directory
- [ ] Author `world-sim-spec-v1.md` — choose static or dynamic mode; define at least one theme
- [ ] Author `magic-circle-consent-v1.md` — adapt participant/authority terminology for the domain
- [ ] Author `artifact-and-mastery-spec-v1.md` — define artifacts and boss challenges; map in-world names
- [ ] Add `world_sim` block to `runtime-config.yaml` with at least a `default_theme`
- [ ] Add `world-sim/*.md` paths to `runtime.additional_specs` in `runtime-config.yaml`
- [ ] In `controllers/runtime_adapters.py`, call `select_world_sim_theme(profile, world_sim_cfg)` inside `build_initial_learning_state` and store result on state
- [ ] Update `interpret_turn_input` to accept `world_sim_theme` kwarg and inject hint block
- [ ] Update the domain system prompt (`prompts/domain-system-override.md`) with conditional persona rendering rules

---

## Domain Extensions

- **Education — MUD Dynamic World Builder:** An advanced dynamic persona that generates 8 narrative constants (zone, protagonist, antagonist, guide NPC, macguffin, variable skin, obstacle theme, failure state) locked for the entire session. See [`domain-packs/education/docs/7-concepts/mud-world-builder.md`](../../domain-packs/education/docs/7-concepts/mud-world-builder.md)

---

## References

- [`domain-adapter-pattern.md`](domain-adapter-pattern.md) — engine contract fields, three-layer distinction (tool-adapters / domain-lib / runtime-adapter)
- [`domain-packs/education/world-sim/world-sim-spec-v1.md`](../../domain-packs/education/world-sim/world-sim-spec-v1.md) — education reference implementation: persona parameters
- [`domain-packs/education/world-sim/magic-circle-consent-v1.md`](../../domain-packs/education/world-sim/magic-circle-consent-v1.md) — education reference implementation: consent activation gate
- [`domain-packs/education/world-sim/artifact-and-mastery-spec-v1.md`](../../domain-packs/education/world-sim/artifact-and-mastery-spec-v1.md) — education reference implementation: reward surface
- [`domain-packs/education/world-sim/mud-world-builder-spec-v1.md`](../../domain-packs/education/world-sim/mud-world-builder-spec-v1.md) — MUD World Builder: advanced dynamic persona (education domain)
- [`../../specs/principles-v1.md`](../../specs/principles-v1.md) — Principle 8 (consent boundary), enforced by magic circle
