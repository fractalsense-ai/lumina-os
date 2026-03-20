# Memory Specification — V1

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-03-05

---

## Overview

Project Lumina uses **indexed generalized memory** — a structured, queryable store of information about the entity being served, the domain, and prior interactions. This is not a transcript store. It is a structured index of facts and states.

Memory in Project Lumina has three layers:
1. **Domain Memory** — the Domain Physics (invariants, artifacts, standing orders) — static per session
2. **Entity Memory** — the entity profile (compressed state, preferences, artifact history) — updated per session
3. **Session Memory** — structured summaries from System Log TraceEvents — per-session ephemeral, summarized to profile

---

## Domain Memory

Domain memory is the domain pack loaded at session start. It is:
- Immutable during the session
- Loaded from disk and hash-verified against the System Logs commitment
- Fully queryable via the RAG layer (see [`../retrieval/rag-contracts.md`](../retrieval/rag-contracts.md))

Domain memory is not "remembered" between sessions — it is always loaded fresh. Consistency is ensured by version control and System Log hash commitments.

---

## Entity Memory

Entity memory is the entity profile. It persists between sessions and is updated at session close.

### What Is Stored

```yaml
# Stored in entity-profile (the education domain names this "student-profile"
# as a domain convention; other domains use names appropriate to their context)
entity_state:
  affect:                     # affect state from last session end
  mastery:                    # per-skill mastery estimates
  challenge_band:              # optimal challenge band (min/max bounds)
  recent_window:              # rolling window state (resets each session)
  challenge: 0.5
  uncertainty: 0.5
  updated_utc: "2026-03-05T..."

session_history:
  total_sessions: 5
  last_session_utc: "2026-03-01T..."
  total_turns: 47

artifacts_earned:
  - artifact_id: linear_equations_basic
    earned_utc: "2026-02-15T..."
    session_id: "<uuid>"
```

### What Is NOT Stored

- Conversation content
- Verbatim responses from the entity/subject
- Any content that would allow re-reading the session like a transcript

### Preferences Memory

Preferences (interests, dislikes) are stored in the entity profile but tagged as immersion-only. They are never used for assessment and are clearly separated from entity state.

---

## Session Memory

During a session, the orchestrator maintains working memory:
- The current compressed state (in memory, not disk)
- The recent window buffer (in memory, updated each turn)
- The current task and its evidence accumulation (in memory, ephemeral)

At session close:
- The final compressed state is written to the entity profile
- A session summary is assembled and the `OutcomeRecord` is appended to the System Logs
- The working memory is discarded (no transcript retention)

---

## Retrieval-Augmented Memory

The RAG layer provides access to:
- Prior System Log records (by session ID, entity ID, or record type)
- Domain pack artifacts and invariants (by ID)
- Evaluation bundles (for boss challenges)

Retrieved content is always cited by artifact ID and version. See [`../retrieval/rag-contracts.md`](../retrieval/rag-contracts.md) for retrieval contracts.

---

## Memory Integrity

- Entity profiles are signed with the hash of their last update in the System Logs
- On load, the profile hash is verified against the System Logs record
- If verification fails, the session cannot proceed until the Domain Authority resolves the discrepancy (see [`../specs/reports-spec-v1.md`](reports-spec-v1.md))

---

## Privacy

- All entity memory is pseudonymous
- No real-identity data is stored in the AI layer
- Session memory is discarded at session close
- Preferences are tagged and isolated from assessment data

---

## Index Structure

The retrieval index schema for memory queries is defined in [`../retrieval/retrieval-index-schema-v1.json`](../retrieval/retrieval-index-schema-v1.json).
