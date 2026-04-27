---
version: 1.0.0
last_updated: 2026-03-20
---

# Novel Synthesis Framework

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-03-18  

---

This document defines how Project Lumina detects, verifies, and records novel synthesis events — moments when the LLM reasoning engine identifies a non-obvious connection or approach that does not match any known pattern in the active domain physics. The framework spans two modular boundaries (domain and system) and provides the telemetry foundation for cross-domain model performance benchmarking.

---

## A. What Is Novel Synthesis?

A **novel synthesis** occurs when the LLM produces a response that the domain's evidence extractors cannot classify using existing rules. In an algebra domain this might be an unrecognized solution method; in an agriculture domain it might be a novel pest-management correlation.

The core problem: LLMs generate enormous volumes of output. Most of it matches known patterns and can be handled deterministically. The rare signal — a genuinely new and useful connection — is buried in noise. Without a structured framework, innovations go unrecorded and the system cannot distinguish between a model that parrots known answers and one that generates genuine insight.

Novel synthesis tracking solves this by:

1. **Isolating the signal from noise** — only flagged, non-obvious connections enter the verification pipeline.
2. **Requiring human confirmation** — the system never self-validates innovation; a domain authority must turn the second key.
3. **Recording lean metadata** — the system log stores only the audit trail (domain, model, timestamp, verdict), not the raw content.
4. **Enabling model benchmarking** — by correlating novel synthesis rates with model identity, the system builds a performance heatmap across domains.

---

## B. The Two-Key Verification Gate

Novel synthesis uses a **two-key gate** — two independent confirmations before the system records an event as validated innovation.

### Key 1 — LLM / Domain Adapter

The first key turns when the domain's evidence extraction pipeline cannot classify the LLM's response using existing rules. This is expressed in the domain physics as a warning invariant with a `signal_type`:

```yaml
# model-packs/<domain>/modules/<module>/domain-physics.yaml
invariants:
  - id: standard_method_preferred
    severity: warning
    check: "method_recognized"
    standing_order_on_violation: request_method_justification
    signal_type: NOVEL_PATTERN
```

When `method_recognized` evaluates to `false`, the invariant fires. The orchestrator:

1. Applies the standing order (`request_method_justification`) — asking the subject to explain their reasoning.
2. Propagates the `signal_type` into the TraceEvent metadata as `novel_synthesis_signal`.
3. If the standing order exhausts without resolution, creates an EscalationRecord with `trigger_type: novel_synthesis_review`.

Key 1 is entirely domain-owned. The engine does not hardcode signal types — it propagates whatever `signal_type` string the domain physics defined on the failing invariant.

### Key 2 — Domain Authority (Human-in-the-Loop)

The second key turns when the Domain Authority reviews the escalation and issues a resolution:

| Verdict | CommitmentRecord `commitment_type` | Effect |
|---------|--------------------------------------|--------|
| Accepted | `novel_synthesis_verified` | Innovation recorded; domain physics may be updated to recognize the pattern in future |
| Rejected | `novel_synthesis_rejected` | Flagged as false positive; `metadata` **MUST** include `denial_rationale` (category + authority note — see below); model may be flagged for reliability concerns |

#### Rejection Denial Rationale

When issuing a `novel_synthesis_rejected` CommitmentRecord, the Domain Authority **must** supply a `denial_rationale` object inside `metadata`:

| Field | Type | Constraints |
|-------|------|-------------|
| `reason_category` | enum | `hallucination` · `out_of_domain` · `logical_error` · `insufficient_evidence` · `duplicate_of_known_pattern` · `other` |
| `authority_note` | string | Authority's written explanation of the denial; max 512 chars |

The `reason_category` gives the SLM a structured signal for corpus indexing and similarity matching. The `authority_note` is the human rationale that the SLM surfaces as prompt context when it detects similar reasoning in a later datastream (see [Section G](#g-rejection-corpus-slm-negative-pre-filter)).

The system does **not** learn the new concept until Key 2 turns. This prevents hallucinated "innovations" from polluting the domain knowledge base.

### Lifecycle Diagram

```
  ┌─────────────────────────────────────────────────────────────┐
  │                    DOMAIN BOUNDARY                          │
  │                                                             │
  │  Evidence Extraction                                        │
  │       │                                                     │
  │       ▼                                                     │
  │  method_recognized == false                                 │
  │       │                                                     │
  │       ▼                                                     │
  │  Invariant fires ──► Standing Order                         │
  │  signal_type:          (request_method_justification)       │
  │  NOVEL_PATTERN              │                               │
  │       │                     ▼                               │
  │       │              Exhausted? ──yes──► EscalationRecord   │
  │       │                                  trigger_type:      │
  │       │                                  novel_synthesis_   │
  │       │                                  review             │
  │       │                                      │              │
  │       │                                      ▼              │
  │       │                              Domain Authority       │
  │       │                              reviews (Key 2)        │
  │       │                                      │              │
  │       │                     ┌────────────────┼──────────┐   │
  │       │                     ▼                ▼          │   │
  │       │              VERIFIED          REJECTED         │   │
  │       │             CommitmentRecord   CommitmentRecord │   │
  └───────│─────────────────────│────────────────│──────────┘   │
          │                     │                │              │
  ┌───────│─────────────────────│────────────────│──────────┐   │
  │       │    SYSTEM BOUNDARY  │                │          │   │
  │       ▼                     ▼                ▼          │   │
  │  TraceEvent            System System Log records verdict       │   │
  │  metadata:             + model_id + model_version       │   │
  │    model_id            + model_pack_id                  │   │
  │    model_version                                        │   │
  │    novel_synthesis_signal                               │   │
  │                                                         │   │
  └─────────────────────────────────────────────────────────┘   │
```
> **Downstream corpora:** Each verdict feeds a domain-scoped corpus. `novel_synthesis_verified` records form the **Verified Synthesis Corpus** (Section H); `novel_synthesis_rejected` records — including their `denial_rationale` — form the **Rejection Corpus** (Section G). The SLM taps both corpora before dispatching to the LLM on subsequent turns.
---

## C. System-Level Telemetry

The system boundary tracks model identity without inspecting domain logic. Every TraceEvent's `metadata` carries:

| Key | Source | Purpose |
|-----|--------|---------|
| `model_id` | Per-request (`ChatRequest.model_id`) | LLM identifier (e.g. `claude-sonnet-4-20250514`) |
| `model_version` | Per-request (`ChatRequest.model_version`) | Model revision/version string |
| `novel_synthesis_signal` | Orchestrator (from failing invariant `signal_type`) | Presence indicates Key 1 has turned |

The system log stores only the **metadata** for the audit — not the raw synthesis content. This creates a reproducible "Map of Innovation" without bloating the system ledger:

- **Tag:** `NOVEL_SYNTHESIS` (the `novel_synthesis_signal` value in TraceEvent metadata)
- **Metadata:** `model_pack_id`, `model_id`, `model_version`, `timestamp_utc`
- **Resolution:** `novel_synthesis_verified` or `novel_synthesis_rejected` CommitmentRecord

---

## D. Compute Efficiency Argument

The novel synthesis framework interacts with two existing efficiency mechanisms:

### Stage 2 Intercept — Glossary Lookups

When a user asks "what is a variable?" in the algebra domain, the glossary intercept pipeline (`detect_glossary_query` in `src/lumina/api/utils/glossary.py`) returns the deterministic definition immediately. This saves 100% of LLM compute for known terms — the LLM is never invoked.

Novel synthesis, by definition, is what the glossary **cannot** handle. It is the complement of deterministic lookup: when no known pattern matches, the system falls through to the LLM for creative reasoning.

### Grounding Anchors

By providing the domain's "truth" up front via the prompt contract — invariants, standing orders, glossary terms, and domain physics — the system enables:

- **Smaller, cheaper models** to explain what larger models would have to discover from scratch.
- **Novel synthesis tracking** to identify where a model adds genuine value beyond the grounding material.

The efficiency argument: if Model A produces the same novel synthesis rate as Model B but costs 10x more, the grounding anchors have made the cheaper model equally capable for that domain. The telemetry makes this comparison possible.

### Tier 3 — Novel Synthesis Corpus Intercept

The novel synthesis framework adds a third efficiency tier at the SLM layer, completing the cost stack:

| Tier | Mechanism | LLM dispatched? |
|------|-----------|-----------------|
| 1 | Glossary intercept — deterministic definition returned before LLM is invoked | Never |
| 2 | Grounding anchors — smaller/cheaper model guided by domain physics truth | Yes, but cheaper |
| 3 | Novel synthesis corpus — SLM replays verified insights; pre-filters rejected reasoning | Never (on hit) |

- **Rejection corpus pre-filter (Section G):** If the outbound reasoning resembles a previously rejected synthesis in the active domain corpus, the SLM attaches the prior `denial_rationale` as prompt context before the LLM call. No compute spent re-traversing logic already determined false.
- **Verified synthesis replay (Section H):** If the outbound reasoning matches a confirmed novel synthesis in the active domain corpus, the SLM serves the verified insight directly without invoking the LLM. No compute spent rediscovering a known truth.

---

## E. Model Performance Benchmarking

Novel synthesis metadata enables three forms of model intelligence:

### 1. LLM Performance Heatmap

By aggregating `novel_synthesis_signal` events grouped by `model_id` x `model_pack_id`, the system builds a performance matrix:

```
                    Education    Agriculture    Lab-Science
claude-sonnet-4       ██████       ███            █████████
gpt-5                 ████         ████████       ██████
gemini-2-ultra        ████████     █████          ████

█ = verified novel synthesis events per 1000 turns
```

If a spike appears when switching a domain from one model to another, the system has discovered which model has better "latent correlation" for that subject matter.

**The "Physics" of the Model:** Some models are better at creative synthesis (connecting disparate dots), while others are better at deterministic logic (following the rules). The heatmap makes this visible at the domain level.

### 2. Domain-to-Model Optimization

The telemetry enables future **dynamic routing**: the system examines historical novel synthesis rates and routes domain packets to the model with the best track record for that domain. This is a Darwinian selection process — models that produce verified insights survive; those that produce noise are deprioritized.

> **Note:** Automatic model routing is a planned future capability. The current slice provides the telemetry foundation only.

### 3. Model Drift Detection

The two-key gate protects against **model collapse**. If a new model version starts hallucinating "novel" ideas that Key 2 (the domain authority) keeps rejecting, the rejection rate spikes. The system can:

- Flag the model version as unreliable for that domain.
- Alert the Meta Authority to consider rolling back to a known stable version.
- Provide evidence for the rollback decision via the System Logs audit trail.

The signal: if the `novel_synthesis_rejected` rate increases significantly after a model update, the provider may have degraded the model's reasoning capabilities. The system catches this immediately because the system-level ledger shows a dip in verified innovation alongside the model version change.

---

## F. Domain Pack Integration

To enable novel synthesis tracking in a domain pack, a domain author adds three elements to the domain physics:

### 1. Warning Invariant with `signal_type`

```yaml
invariants:
  - id: standard_method_preferred
    description: >
      Non-standard approaches are acceptable but flagged for review.
    severity: warning
    check: "method_recognized"
    standing_order_on_violation: request_method_justification
    signal_type: NOVEL_PATTERN
```

The `signal_type` value is a free-form string. The engine propagates it verbatim — the domain owns the vocabulary.

### 2. Standing Order

```yaml
standing_orders:
  - id: request_method_justification
    action: request_method_justification
    trigger_condition: standard_method_preferred
    max_attempts: 1
    escalation_on_exhaust: false
    description: >
      Acknowledge the non-standard approach and ask the subject
      to explain their reasoning. Flag for Domain Authority review.
```

### 3. Escalation Trigger

```yaml
escalation_triggers:
  - id: novel_pattern_review
    condition: >
      standard_method_preferred invariant fired and the method
      is unrecognized after justification request.
    target_role: teacher
    sla_minutes: 120
```

No changes to `src/lumina/` are required. The engine's generic `signal_type` propagation handles any domain that wires these fields.

---

## G. Rejection Corpus: SLM Negative Pre-Filter

When Key 2 produces a `novel_synthesis_rejected` CommitmentRecord, that record — including its `denial_rationale` — is indexed into an **active-domain-scoped** rejection corpus available to the SLM.

### Purpose

An LLM that produced a false-positive synthesis once will, operating on the same or similar input, likely produce it again. Without a record of the rejection and its rationale, the system would:

1. Invoke an expensive LLM call.
2. Receive the same flawed reasoning.
3. Escalate to the Domain Authority again for an identical verdict.

The rejection corpus short-circuits this loop.

### SLM Intercept Behaviour

Before the SLM forwards a datastream to a high-weight LLM call, it performs a similarity check against the domain's rejection corpus:

| Outcome | Action |
|---------|--------|
| **No match** | Datastream proceeds to LLM normally |
| **Match (default policy)** | SLM prepends the prior `denial_rationale` summary as prompt context; TraceEvent `metadata` carries `prior_rejection_match: true` |
| **Match (block policy)** | LLM call is suppressed entirely; SLM returns the denial rationale summary directly as the response |

The default policy is **flag + attach context** — the LLM is still invoked but now sees the prior verdict as a grounding anchor, steering it away from the rejected line of reasoning.

### Domain Physics Opt-In for Hard Block

A domain author can escalate from attach-context to hard-block by setting a flag in domain physics:

```yaml
slm_config:
  prior_rejection_policy: block   # default: attach_context
```

With `block`, if the SLM detects a semantic match above threshold, the LLM call is suppressed. The SLM returns the denial rationale as context for the caller without consuming LLM compute.

### What Gets Indexed

Each rejection corpus entry contains:

- `record_id` — CommitmentRecord UUID (for audit trail back-reference)
- `model_pack_id` — corpus is scoped to this model-pack
- `rejection_summary_hash` — hash of the original synthesis signal context (never raw transcript)
- `denial_rationale.reason_category` — structured reason for SLM similarity matching
- `denial_rationale.authority_note` — human rationale, surfaced as prompt context when the SLM fires

> **Privacy boundary:** The corpus indexes hashes and structured fields only. Raw transcript content or subject-identifiable data is never stored in the rejection corpus.

---

## H. Verified Synthesis Corpus: SLM Replay Path

When Key 2 produces a `novel_synthesis_verified` CommitmentRecord, that verified insight is indexed into an **active-domain-scoped** verified synthesis corpus available to the SLM.

### Purpose

A verified novel synthesis is a genuine new pattern confirmed by a human authority. Invoking the full LLM pipeline again to reproduce a conclusion already confirmed is pure compute waste. The verified synthesis corpus enables the SLM to serve confirmed insights directly — analogous to how the Stage 2 glossary intercept serves known definitions, but for dynamically discovered knowledge rather than pre-authored glossary entries.

### SLM Replay Behaviour

Before the SLM forwards a datastream to the LLM, it performs a similarity check against the domain's verified synthesis corpus:

| Outcome | Action |
|---------|--------|
| **No match** | Datastream proceeds to LLM normally |
| **Match above replay threshold** | SLM serves the verified insight directly; LLM is not invoked; TraceEvent `metadata` carries `synthesis_replay: true` |

The `synthesis_replay: true` tag in TraceEvent `metadata` ensures the System Logs audit trail captures the efficiency gain without losing traceability — an auditor can trace back to the original `novel_synthesis_verified` CommitmentRecord via the corpus entry's `record_id`.

### Replay Threshold

The similarity threshold governing replay is domain-configurable:

```yaml
slm_config:
  synthesis_replay_threshold: 0.92   # default; range 0.0–1.0
```

A higher threshold means the SLM only replays when extremely confident in the match, falling back to the LLM for borderline cases. A lower threshold trades accuracy for efficiency. The default is conservative to protect against false-positive replays serving incorrect conclusions.

### Relationship to Glossary Intercept (Tier 1)

The glossary intercept (Tier 1) operates on pre-authored, static knowledge in the domain physics. The verified synthesis corpus (Tier 3 replay) operates on *dynamically discovered* knowledge that was unknown at domain pack authoring time. Together they form a two-layer deterministic pre-filter in front of the LLM:

```
Incoming datastream
     │
     ▼
Glossary check (Tier 1) ──hit──► Return deterministic definition
     │ miss
     ▼
Verified synthesis corpus check (Tier 3 — replay) ──hit──► Return verified insight
     │ miss
     ▼
Rejection corpus check (Tier 3 — pre-filter) ──hit──► Attach denial context (or block LLM)
     │
     ▼
LLM dispatch
```

---

## SEE ALSO

- [`domain-adapter-pattern(7)`](domain-adapter-pattern.md) — Engine contract fields, three-layer distinction, Phase A/B lifecycle
- [`nlp-semantic-router(7)`](nlp-semantic-router.md) — Two-tier NLP architecture, glossary intercept
- [`dsa-framework-v1`](../../specs/dsa-framework-v1.md) — D.S.A. structural schema underlying the PPA orchestrator
- [`trace-event-schema`](../../ledger/trace-event-schema.json) — TraceEvent schema with `novel_synthesis_flagged` event type and `model_id`/`model_version` metadata keys
- [`commitment-record-schema`](../../ledger/commitment-record-schema.json) — CommitmentRecord with `novel_synthesis_verified` / `novel_synthesis_rejected` types
- [`escalation-record-schema`](../../ledger/escalation-record-schema.json) — EscalationRecord with `novel_synthesis_review` trigger type
