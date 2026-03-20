# RAG Contracts — Project Lumina

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

The **RAG (Retrieval-Augmented Generation) layer** governs what the orchestrator may retrieve, from where, when, and by whom. This document specifies the grounding contract: the rules that ensure the orchestrator's responses are anchored to authorized, verified content — not hallucinated.

---

## Core Grounding Contract

Every orchestrator response that uses retrieved content must:

1. **Cite the retrieved artifact** by ID and version
2. **Verify the artifact hash** against the System Logs commitment before use
3. **Not use content that fails hash verification** — escalate instead
4. **Not retrieve beyond the authorized scope** for the current session
5. **Not hallucinate** — if required context cannot be retrieved, escalate rather than guess

A response that uses retrieved content without citation is a violation of the grounding contract.

---

## Retrieval Targets

### What May Be Retrieved

| Target Type | Description | Who May Request |
|------------|-------------|-----------------|
| Domain Pack | Invariants, standing orders, artifacts, subsystem config | Orchestrator (session-scoped) |
| Tool Adapter Definitions | Input/output schemas for authorized tools | Orchestrator (session-scoped) |
| Mastery Artifacts | Artifact definitions and unlock conditions | Orchestrator (session-scoped) |
| Boss Challenge Bundles | Task definitions for artifact assessment | Orchestrator (boss challenge only) |
| System Log TraceEvents (structured fields only) | Prior decisions, standing order invocations | Domain Authority (audit), Orchestrator (limited) |
| Subject Profile | Compressed state, preferences, consent record | Orchestrator (own session only) |
| Prior Session Summaries | Aggregate session outcomes (no transcripts) | Domain Authority, Meta Authority |
| Evaluation Bundles | Test tasks for harness evaluation | Evaluation harness only |

### What May NOT Be Retrieved

| Prohibited Target | Reason |
|------------------|--------|
| Conversation transcripts | Not stored; retrieval would be a privacy violation |
| Raw System Log record content | Only structured fields; never free-text payloads |
| Another subject's profile | Privacy isolation |
| Domain packs outside current scope | Domain-bounded operation |
| Content from unapproved external sources | Domain Physics must authorize all retrieval targets |

---

## Retrieval Order

The orchestrator follows a specific retrieval order to ensure determinism and auditability:

1. **Structured filters first** — query by explicit identifiers (artifact ID, session ID, domain pack ID)
2. **Semantic search second** — if no exact match, use semantic similarity within the authorized corpus
3. **Rerank and verify** — rerank results by relevance; verify each result's hash against System Log
4. **Cite or escalate** — if no verified result is found, escalate rather than proceed without grounding

---

## Retrieval Scope Boundaries

### Session-Level Scope

A session may only retrieve from:
- The domain pack loaded for this session (verified hash)
- The subject profile for the current session subject (pseudonymous)
- Artifacts defined within the current domain pack
- Boss challenge bundles authorized by the current domain pack

### Domain Authority Scope

A Domain Authority reviewing a session may retrieve:
- System Log structured fields for sessions within their governed domains
- Subject progress summaries (pseudonymous, no transcripts)
- Domain pack versions within their authored scope

### Meta Authority Scope

A Meta Authority may retrieve:
- Everything a Domain Authority under them may retrieve
- Aggregate reports across all governed domains
- Escalation records for their scope

---

## Retrieval Citation Format

All retrieved content used in a response must be cited using this format:

```
[Retrieved: {artifact_id} v{version} — hash verified]
```

Examples:
- `[Retrieved: domain/org/algebra-level-1/v1 v0.2.0 — hash verified]`
- `[Retrieved: artifact/linear_equations_basic — hash verified]`

If hash verification fails:
- Do not use the content
- Append a TraceEvent: `event_type: retrieval_hash_mismatch`
- Escalate if the content is required for the session to proceed

---

## Out-of-Scope Retrieval Attempts

If the orchestrator detects that a request would require out-of-scope retrieval:
- Do not perform the retrieval
- Redirect to in-scope content
- If the session cannot proceed without out-of-scope content, escalate

Repeated out-of-scope retrieval attempts by a session are an escalation trigger.

---

## Grounding Failure Protocol

If grounding fails (required content cannot be retrieved and verified):

1. **Do not generate** — do not produce a response based on ungrounded content
2. **Disclose** — inform the subject using domain vocabulary: "I need to check something with the domain authority before we continue"
3. **Escalate** — create an `EscalationRecord` with trigger: `grounding_failure`
4. **Freeze** — pause the session until the Meta Authority resolves the escalation

---

## References

- [`retrieval-index-schema-v1.json`](retrieval-index-schema-v1.json) — retrieval index schema
- [`../standards/lumina-core-v1.md`](../standards/lumina-core-v1.md) — conformance requirements (Section 5)
- [`../specs/memory-spec-v1.md`](../specs/memory-spec-v1.md) — memory layer overview
- [`../standards/system-log-v1.md`](../standards/system-log-v1.md) — System Log record types
