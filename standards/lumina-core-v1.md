# Lumina Core V1 — Meta Specification

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Purpose

This document defines the meta-specification that **all Project Lumina domain packs and implementations must conform to**. It establishes the minimum structural requirements, naming conventions, and protocol obligations.

A domain pack or implementation that does not satisfy the requirements in this document is non-conformant and must not be used in a production Lumina session.

---

## 1. Domain Pack Conformance

Every domain pack must include the following artifacts:

| Artifact | Required | Schema |
|----------|----------|--------|
| `domain-physics.yaml` | Yes | [`domain-physics-schema-v1.json`](domain-physics-schema-v1.json) |
| `domain-physics.json` | Yes (derived) | Same schema |
| `student-profile-template.yaml` | Yes | [`student-profile-schema-v1.json`](student-profile-schema-v1.json) — the education-domain instantiation of the general subject profile pattern; other domains should provide a domain-appropriate profile |
| `CHANGELOG.md` | Yes | Semver entries |
| `prompt-contract-schema.json` | Yes | Extends [`prompt-contract-schema-v1.json`](prompt-contract-schema-v1.json) — domain-specific prompt constraints must extend the universal base schema |

Optional but recommended:
- `tool-adapters/*.yaml` — one per tool, conforming to [`tool-adapter-schema-v1.json`](tool-adapter-schema-v1.json)
- `example-student-*.yaml` — example profiles for testing

### 1.1 Domain Physics Requirements

A conformant `domain-physics.yaml` must declare:

- `id`: globally unique identifier (format: `domain/{org}/{name}/v{major}`)
- `version`: semver string
- `domain_authority`: name/role of the human author
- `meta_authority_id`: id of the domain pack one level above (or `"root"` for top-level)
- `invariants`: list of at least one invariant with `severity: critical`
- `standing_orders`: list of at least one standing order
- `escalation_triggers`: at least one trigger referencing a standing order
- `artifacts`: list of recognized mastery artifacts (may be empty for v0 packs)
- `subsystem_configs`: optional map of domain-specific subsystem parameter blocks, keyed by subsystem ID (e.g. `zpd_monitor` for learner-facing education domains). Each value is a free-form object understood only by that subsystem. Omit for domains with no configurable subsystems.
- `requires_consent`: consent requirement flag (required for human-facing domains that must enforce the magic-circle consent principle; omit for machine-facing domains)

### 1.2 Invariant Severity Levels

| Severity | Meaning | Required Action |
|----------|---------|-----------------|
| `critical` | Violation halts autonomous action | Immediate standing order or escalation |
| `warning` | Violation triggers a standing order | Standing order response within session |

### 1.3 Standing Order Bounds

Standing orders define the **bounded automated responses** the orchestrator may take without human escalation. Each standing order must declare:
- `trigger_condition`: which invariant or drift condition activates it
- `action`: the specific automated action (e.g., `zpd_scaffold`, `request_more_steps`)
- `max_attempts`: how many times this order may be applied before escalation
- `escalation_on_exhaust`: whether to escalate when `max_attempts` is reached

---

## 2. Causal Trace Ledger (CTL) Conformance

Every Lumina system must maintain a CTL-conformant ledger. Requirements:

- **Append-only**: records may not be modified or deleted
- **Hash-chained**: each record includes the hash of the previous record
- **No transcripts**: records must not contain raw conversation content
- **Pseudonymous**: actor identifiers are pseudonymous; real-identity mapping is held externally
- **Record types**: all systems must support `CommitmentRecord` and `TraceEvent` at minimum

See [`causal-trace-ledger-v1.md`](causal-trace-ledger-v1.md) for the full CTL specification.

---

## 3. Compressed State Conformance

For domains that implement subject state tracking, state must be represented using the compressed state schema. The schema is domain-agnostic; the sensors that populate it are defined per domain in the domain pack's `sensors/` directory.

> **Note:** The fields below reflect the education-domain instantiation. Other domains use the same schema structure but populate fields via their own domain sensor arrays (e.g., an agriculture domain might use different signal sources for `salience` and `mastery`). See [`domain-sensor-array-v1.md`](domain-sensor-array-v1.md) for the sensor array specification.

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `salience` | float | 0..1 | How engaged/focused the subject is |
| `valence` | float | -1..1 | Emotional tone (-1 = negative, +1 = positive) |
| `arousal` | float | 0..1 | Activation level (0 = flat, 1 = highly activated) |
| `mastery` | dict[skill→float] | 0..1 per skill | Current mastery estimate per skill |
| `challenge` | float | 0..1 | Estimated challenge level of current task |
| `uncertainty` | float | 0..1 | Orchestrator's uncertainty about subject state |
| `challenge_band` | dict | min/max challenge | Optimal challenge range for the subject (min/max bounds). In education contexts this corresponds to the Zone of Proximal Development (ZPD). |

See [`compressed-state-schema-v1.json`](compressed-state-schema-v1.json) for the JSON Schema.

---

## 4. Naming and Terminology

All Project Lumina documents and code must use the following canonical terminology:

| Canonical Term | Description | Do NOT use |
|----------------|-------------|------------|
| **Project Lumina** | The overall system | "Spotter" |
| **Causal Trace Ledger (CTL)** | The append-only accountability ledger | "Flight Data Recorder", "FDR" |
| **Domain Authority** | The human expert who authors the domain | "Master" |
| **D.S.A. Framework** | Domain, State, Action | Other acronyms |
| **Meta Authority** | Domain Authority one level above | "Super-admin" |
| **Domain Physics** | The authored ruleset (YAML) | "Rules file" |
| **Standing Order** | A bounded automated response | "Auto-response", "rule" |
| **Challenge Band** | Optimal challenge range for the subject (min/max bounds) | "Difficulty range", "ZPD band" |

---

## 5. RAG Layer Conformance

Systems using retrieval-augmented generation must conform to the grounding contract:

- Cite retrieved artifacts by ID and version in every response that uses retrieved content
- If required context cannot be retrieved, escalate rather than hallucinate
- Retrieval scope is bounded by the current Domain Physics — do not retrieve beyond authorized scope
- No retrieval of PII beyond what is declared in the student profile schema

See [`../retrieval/rag-contracts.md`](../retrieval/rag-contracts.md) for the full RAG contract.

---

## 6. Versioning

This meta-specification itself is versioned. Breaking changes to this specification:
- Increment the major version
- All conformant domain packs must declare the lumina-core version they target
- A domain pack targeting `lumina-core-v1` is not required to change until `lumina-core-v2` is released

---

## 7. Conformance Checklist

Before publishing a domain pack or implementation:

- [ ] Domain Physics YAML validates against `domain-physics-schema-v1.json`
- [ ] At least one `critical` invariant is defined
- [ ] All standing orders have `max_attempts` and `escalation_on_exhaust` set
- [ ] Subject profile template validates against the appropriate profile schema for the domain
- [ ] CHANGELOG.md is present and up to date
- [ ] CTL integration is append-only and hash-chained
- [ ] No transcript content is stored in the CTL
- [ ] All identifiers are pseudonymous
- [ ] Terminology conforms to Section 4
- [ ] If the domain is human-facing (`requires_consent: true`), a consent record is required before the session begins
- [ ] If the domain is learner-facing, `subsystem_configs.zpd_monitor` (or equivalent subsystem config) is present and drift thresholds are set

---

*This specification is maintained by the Project Lumina governance body. All changes require a Major version bump.*