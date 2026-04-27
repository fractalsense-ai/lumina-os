# World Simulation Specification — Education Domain (V1)

> **Domain scope:** This world simulation specification is for the education domain. Other domains may adapt this pattern for their own simulation/immersion contexts (e.g., operational simulations in agriculture, scenario-based training in corporate).

**Version:** 1.2.0  
**Status:** Active  
**Last updated:** 2026-03-13

---

## Overview

Project Lumina sessions may operate within a **text-based world simulation** — a narrative context that makes abstract domain content concrete and engaging. The world simulation is a structured immersion layer, not a separate system. It runs on top of the D.S.A. Framework and is bounded by the same Domain Physics.

---

## Persona Model

The world simulation is the **education domain's persona** — the narrative identity the AI adopts for a session. Three files work together to define it:

| File | Role |
|---|---|
| This file (`world-sim-spec-v1.md`) | Persona parameters: theme, setting, in-world labels for tasks and artifacts |
| [`magic-circle-consent-v1.md`](magic-circle-consent-v1.md) | Activation gate: the persona does not start until the participant gives informed consent. The consent is what "activates" the persona. |
| [`artifact-and-mastery-spec-v1.md`](artifact-and-mastery-spec-v1.md) | Reward surface: earned artifacts may carry in-world names. Only the display name is persona-skinned; mastery thresholds and skills required are invariant. |

> **The persona is the skin. Domain physics is the skeleton. The skeleton never changes because the skin does.**

The persona may be **static** (a single fixed theme for all sessions) or **dynamic** (theme selected at session start based on entity preferences). Both modes are valid. The education domain uses dynamic selection. See [`docs/7-concepts/world-sim-persona-pattern.md`](../../../docs/7-concepts/world-sim-persona-pattern.md) for the generalized pattern that other domains can adopt.

---

## Purpose

The world simulation serves two goals:
1. **Engagement** — a narrative context makes practice feel meaningful rather than rote
2. **Grounding** — domain concepts are anchored to concrete situations

Examples:
- Algebra problems as "calculating supplies for a space mission" *(education domain)*
- Chemistry as "running a lab at a research station" *(education domain)*
- History as "advising a historical figure" *(education domain)*
- Monitoring crop health as "managing a virtual farm" *(agriculture domain)*
- Treatment protocol selection as "running a field hospital" *(medical domain)*

The narrative is cosmetic. The mathematical or conceptual content is unchanged. Equivalence checks, invariant rules, and mastery thresholds are the same regardless of theme.

---

## World Parameters

A world simulation is defined by parameters in the domain pack or session configuration:

```yaml
world_sim:
  enabled: true
  theme: "space_exploration"  # matches entity preferences if available
  setting_description: "You are the mission mathematician aboard the Helios research vessel."
  artifact_framing: "mission_badge"  # how artifacts are presented in-world
  task_framing: "mission_briefing"   # how tasks are presented in-world
  exit_phrase: "end mission"         # in-world equivalent of "exit session"
```

### Dynamic Theme Selection

If the entity profile includes preferences, the world simulation theme is selected dynamically at session start using `select_world_sim_theme()` in `controllers/runtime_adapters.py`. The selected theme is stored on the domain state object and injected as a context hint on every turn. Selection rules:
- Use a theme that maps to a preference if one is available
- Fall back to the domain pack's default theme
- Never select a theme the entity has listed as a dislike
- Theme selection is recorded in the session-open `CommitmentRecord`

---

## Invariants in World Context

Domain invariants apply regardless of world framing. Examples:

- `equivalence_preserved` — "Your equation must stay balanced — the mission computer won't accept unbalanced equations"
- `show_work_minimum` — "The mission log requires at least three steps to verify your calculations"
- `no_illegal_operations` — "You can't divide mission time by zero — that's a mission abort condition"

The AI may use in-world language to communicate invariant violations, but the underlying check is identical to non-world sessions.

---

## Narrative Boundaries

The world simulation is bounded:
- The narrative may not introduce domain content not in the Domain Physics
- The AI may not invent rules, exceptions, or workarounds within the narrative framing
- If the entity asks the AI to play a character who would "know the answer," the AI must maintain the boundary: "Even in this story, I can only help you work through the steps — I can't just give you the answer."
- The exit clause always works: saying "exit session" (or the in-world equivalent) always ends the session cleanly

---

## Consent in World Context

The magic circle consent must occur before the world simulation begins. The consent must explicitly mention:
- That the session will use a fictional narrative
- What the in-world exit phrase is
- That the narrative is a session context, not entertainment

The narrative frame does not reduce or modify any consent obligations.

See [`magic-circle-consent-v1.md`](magic-circle-consent-v1.md) for the full consent specification.

---

## Artifact Presentation

Mastery artifacts may be presented within the world simulation context. Examples:

- "Linear Equations — Foundations" becomes "Mission Clearance: Navigation Calculations"
- The artifact's functional definition (mastery threshold, skills required) is unchanged
- The in-world presentation name is stored separately from the functional artifact definition

---

## Limitations

- World simulation is not currently specified for multi-player or collaborative sessions
- Session transcripts are still not stored — the narrative content is ephemeral
- World parameters are advisory for the orchestrator; they do not override Domain Physics
- Not all domains require world simulation; it is opt-in via domain pack configuration
- Outcome scores and assessments are domain-specific; the world simulation does not alter how the domain lib evaluates performance

---

## MUD World Builder Extension

The education domain also ships an advanced dynamic persona layer: the **MUD World Builder**. It supplements (does not replace) the theme selection above. Where theme selection picks a broad framing (`mission_briefing`, `field_observation`, etc.), the MUD World Builder generates 8 locked narrative constants — zone, protagonist, antagonist, guide NPC, macguffin, variable skin, obstacle theme, and failure state — and holds them identical across every turn of the session.

See [`mud-world-builder-spec-v1.md`](mud-world-builder-spec-v1.md) for the full specification.
