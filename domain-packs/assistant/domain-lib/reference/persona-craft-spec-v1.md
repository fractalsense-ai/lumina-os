# Persona-Craft Specification — v1

<!-- version: 0.1.0 -->
<!-- last_updated: 2026-04-21 -->
**Module ID**: `domain/asst/persona-craft/v1`
**Domain**: assistant
**Version**: 0.1.0
**Last updated**: 2026-04-21

---

## Purpose

The persona-craft module provides a conversational interface for building and
persisting a custom AI personality on the actor profile.  Once set, the
persona overlay is injected into every response across all assistant modules
via the prompt packet assembly layer.

This module is the **prototype for the education domain world-builder**.
The same `persona_engine.py` and `PersonaOverlay` pattern will power the
education domain's antagonist/protagonist/narrator system, where curriculum
content (math, language arts) becomes in-world challenges.

---

## Task Shape

Short multi-turn setup conversation.  The user may update their persona at
any time by routing back to this module with intent `"persona"`.

```
User → expresses desire to change persona
     → NLP pre-interpreter detects persona keywords → sets persona_keywords_detected: true
     → intent classifier → intent_type: "persona"
     → domain_step routes to domain/asst/persona-craft/v1
     → Guided setup conversation (1–4 turns)
     → domain_step calls update_persona() + build_overlay()
     → PersonaState saved to profile; PersonaOverlay injected going forward
```

---

## Archetype Reference

| Archetype     | Label                | Tone                                    |
|---------------|----------------------|-----------------------------------------|
| `neutral`     | Default Assistant    | Helpful, clear, professional            |
| `professional`| Professional         | Formal, precise, measured               |
| `casual`      | Casual Friend        | Relaxed, warm, direct                   |
| `sarcastic`   | Sarcastic Commentator| Dry wit, mild mockery                   |
| `gremlin`     | Chaos Gremlin        | Trash talk, ribbing, chaotic energy     |
| `mentor`      | Tough Mentor         | Blunt feedback, no coddling             |
| `hype`        | Hype Machine         | Enthusiastic, encouraging, over the top |
| `custom`      | Custom               | Derived entirely from `traits[]`        |

The `custom` archetype is the primary extension hook for the education
world-builder.  The user (or the world-builder system) populates `traits[]`
with descriptors like `"narrator who speaks in riddles"` or
`"stern dungeon keeper, rewards correct answers with ammo"`.

---

## Intensity Dial

`intensity` (0.0–1.0) controls how strongly the persona is expressed:

- `0.0` — persona is off; neutral assistant behavior regardless of archetype
- `0.1–0.4` — subtle flavor; tone present but not dominant
- `0.5–0.8` — noticeable character; clearly expressive
- `0.9–1.0` — full character; style applied consistently in every response

Per-module intensity caps apply automatically:

| Module                         | Cap  | Reason                                 |
|--------------------------------|------|----------------------------------------|
| `domain/asst/planning/v1`      | 0.6  | Preserve task structure                |
| `domain/asst/domain-authority/v1` | 0.3 | Governance requires measured tone    |

---

## Persona Name

The optional `name` field lets the user name their character (e.g., "Rex",
"Grim", "Professor Chaos").  The compiled `style_directive` prefixes
responses with `You are "{name}".` when set.

In the education world-builder, `name` will hold the narrator identity
(e.g., "The Keeper of the Shifting Dungeon").

---

## Safety Model

Two independent layers:

1. **`content_safety_hard`** (every module) — escalates on actual harm:
   violence, self-harm, abuse, illegal activity incitement.  Applies to
   generated responses.

2. **`persona_safe`** (this module only) — deterministic gate on persona
   *definitions* via `is_safe_persona()`.  Rejects definitions that
   explicitly target self-harm or abuse vectors.

**Permitted** (above the floor): trash talk, sarcasm, ribbing, dark humor,
bluntness, mockery, profanity (if opted in via `allowed_behaviors`).

---

## Hard Limits

`hard_limits[]` on the actor profile is append-only.  Any actor or DA can
add exclusions (e.g., `"no personal insults"`, `"no profanity"`).  Neither
can remove existing limits.  This preserves governance and parental-control
use cases without requiring a separate permissions layer.

---

## Evidence Contract

Same as the domain-wide schema, plus the persona engine adds:

| Field                  | Type   | Source              |
|------------------------|--------|---------------------|
| `persona_update`       | dict   | Extracted by domain_step from user intent |
| `persona_safety_check` | bool   | Result of `is_safe_persona()`             |

---

## Invariants

| ID                  | Severity | Standing Order         |
|---------------------|----------|------------------------|
| `content_safety_hard` | critical | `safety_intervene` → escalate to DA |
| `persona_safe`       | critical | `reject_unsafe_persona` (max 3, no escalation) |

---

## SEE ALSO

- `domain-lib/persona_engine.py` — PersonaState, PersonaOverlay, build_overlay()
- `modules/conversation/domain-physics.json` — default landing module
- `docs/7-concepts/context-is-not-conversation.md` — why state lives on the profile
- `docs/7-concepts/ai-governance-principles.md` — safety invariant rationale
