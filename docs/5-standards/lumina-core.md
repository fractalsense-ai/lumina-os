---
version: "1.1.0"
last_updated: "2026-03-13"
---

# Lumina Core V1 — Meta Specification

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-03-013

---

## Purpose

This document defines the meta-specification that **all Project Lumina domain packs and implementations must conform to**. It establishes the minimum structural requirements, naming conventions, and protocol obligations.

A domain pack or implementation that does not satisfy the requirements in this document is non-conformant and must not be used in a production Lumina session.

---

## 1. Domain Pack Conformance

Every domain pack must include the following artifacts:

| Artifact | Required | Schema |
|----------|----------|--------|
| `domain-physics.json` | Yes | [`domain-physics-schema-v1.json`](domain-physics-schema-v1.json) |
| `entity-profile-template.yaml` | Yes | Domain-specific subject profile schema in `schemas/` (see note below) |
| `CHANGELOG.md` | Yes | Semver entries |
| `prompt-contract-schema.json` | Yes | Extends [`prompt-contract-schema-v1.json`](prompt-contract-schema-v1.json) — domain-specific prompt constraints must extend the universal base schema |

Optional but recommended:
- `tool-adapters/*.yaml` — one per tool, conforming to [`tool-adapter-schema-v1.json`](tool-adapter-schema-v1.json)
- `example-entity-*.yaml` — example profiles for testing
- `docs/` — domain-scoped man-page documentation tree (see §1.0a)

> **Subject profile schema note:** Each domain pack defines its own subject profile schema in its `schemas/` directory (e.g., [`domain-packs/education/schemas/student-profile-schema-v1.json`](../domain-packs/education/schemas/student-profile-schema-v1.json) for education). The entity profile template is named according to the domain's own conventions (e.g., `student-profile-template.yaml` for education, `operator-profile-template.yaml` for agriculture) and must validate against that domain-specific schema.

### 1.0 Domain Structure Contract

To keep domain ownership explicit and avoid cross-domain coupling, packs must follow this contract:

- **Pack-level domain folder** (`domain-packs/{domain}/`) owns domain-wide context and contracts.
- **Module-level folder** (`domain-packs/{domain}/{module}/`) owns module truth: invariants, standing orders, escalation triggers, thresholds/tolerances.
- **`domain-lib/`** holds deterministic domain estimation/reference specifications used by domain-lib implementations.
- **`world-sim/`** is optional and separate from `domain-lib/`; it provides interaction/world framing, not normative thresholds.
- **`tool-adapters/`** are active deterministic tools and must be explicitly linked from module `domain-physics` via `tool_adapters` IDs.
- **`docs/`** mirrors the root documentation man-page sections (1–8). Required sections: `1-commands/`, `3-functions/`, `7-concepts/`. Optional: `2-syscalls/`, `4-formats/`, `5-standards/`, `6-examples/`, `8-admin/`. See [`domain-pack-anatomy(7)`](../docs/7-concepts/domain-pack-anatomy.md) §H for full details.

Runtime configuration files are wiring surfaces (paths, adapter bindings, runtime flags). Normative thresholds/tolerances and standing-order semantics belong in module `domain-physics`, not runtime wiring.

Operational policy truth for a module is the module `domain-physics.json` artifact. Any material policy update requires: semantic version update and System Log `CommitmentRecord` hash commitment before activation.

### 1.1 Domain Physics Requirements

A conformant `domain-physics.json` must declare:

- `id`: globally unique identifier (format: `domain/{org}/{name}/v{major}`)
- `version`: semver string
- `admin`: name/role of the human author
- `meta_authority_id`: id of the domain pack one level above (or `"root"` for top-level)
- `invariants`: list of at least one invariant with `severity: critical`
- `standing_orders`: list of at least one standing order
- `escalation_triggers`: at least one trigger referencing a standing order
- `artifacts`: list of recognized mastery artifacts (may be empty for v0 packs)
- `subsystem_configs`: optional map of domain-specific subsystem parameter blocks, keyed by subsystem ID (e.g. `zpd_monitor` for education, `soil_health_monitor` for agriculture). Each value is a free-form object understood only by that subsystem. Omit for domains with no configurable subsystems.
- `requires_consent`: consent requirement flag (required for human-facing domains that must enforce the consent boundary principle — Principle 8; omit for machine-facing domains)

### 1.2 Invariant Severity Levels

| Severity | Meaning | Required Action |
|----------|---------|-----------------|
| `critical` | Violation halts autonomous action | Immediate standing order or escalation |
| `warning` | Violation triggers a standing order | Standing order response within session |

### 1.3 Standing Order Bounds

Standing orders define the **bounded automated responses** the orchestrator may take without human escalation. Each standing order must declare:
- `trigger_condition`: which invariant or drift condition activates it
- `action`: the specific automated action (e.g., `request_more_steps`, `reduce_challenge`)
- `max_attempts`: how many times this order may be applied before escalation
- `escalation_on_exhaust`: whether to escalate when `max_attempts` is reached

### 1.4 Tool-Physics Linkage

If a module uses tool adapters, its `domain-physics` must declare `tool_adapters` IDs. Each declared ID must resolve to a tool adapter contract file in that module or domain folder. This keeps tool usage bounded by authored domain truth.

Domain-lib runtime components consume structured signals (including tool-adapter outputs) and produce machine-readable state summaries. The orchestrator remains the policy enforcement point that evaluates module invariants and resolves standing-order/escalation outcomes.

---

## 2. Global System Conformance

The top-level Conversational Interface (CI) layer — the rules that govern every Lumina session regardless of domain — must be managed with the same rigor as domain packs: authored in a structured YAML source, validated against a JSON Schema, and committed to a dedicated system log before taking operational effect.

### 2.0 System Physics Artifact Requirements

The system layer must include the following artifacts:

| Artifact | Required | Schema |
|----------|----------|--------|
| `cfg/system-physics.yaml` | Yes | [`system-physics-schema-v1.json`](system-physics-schema-v1.json) |
| `cfg/system-physics.json` | Yes (derived) | Same schema |
| `specs/global-system-prompt-v1.md` | Yes (rendered view) | Derived from `cfg/system-physics.yaml`; must not diverge |

`cfg/system-physics.json` is the compiled form of the YAML source. Its SHA-256 hash is what gets committed to the system log via a `CommitmentRecord (system_physics_activation)`. The markdown rendering in `specs/global-system-prompt-v1.md` is kept for human readability but is **not** the source of truth.

### 2.1 System Physics Requirements

A conformant `cfg/system-physics.yaml` must declare:

- `id`: globally unique identifier (format: `system/{org}/{name}/v{major}`)
- `version`: semver string
- `meta_authority_id`: id of the Meta Authority responsible (or `"root"` for top-level governance body)
- `conforms_to`: the `lumina-core` version this document targets
- `invariants`: at least one invariant with `severity: critical`
- `standing_orders`: at least one standing order with `max_attempts` and `escalation_on_exhaust`
- `escalation_triggers`: at least one trigger pointing to `target_role: meta_authority`
- `ci_output_contract`: structured rules governing CI output behaviour (output_mode, chain_of_thought, raw_json_output, grounding_requirement, capability_claims, internal_state_disclosure)

### 2.2 System Log

The system layer maintains its **own System Log**, separate from domain/session CTLs but conforming to the same record schemas (`CommitmentRecord`, `TraceEvent`, `EscalationRecord`).

- Storage path convention: `LUMINA_LOG_DIR/system/` (or equivalent configured path)
- System Log must be append-only and hash-chained, same as domain/session CTLs
- Every activation of a new `cfg/system-physics.json` requires a `CommitmentRecord` with `commitment_type: system_physics_activation` and `subject_hash` set to the SHA-256 of the compiled JSON before it takes effect
- Rollbacks require `commitment_type: system_physics_rollback`

### 2.3 Cross-Ledger Hash Reference

Every domain/session `TraceEvent` record **SHOULD** include `system_physics_hash` in its `metadata` block — the SHA-256 of the active `cfg/system-physics.json` at the time of the event.

This creates an auditable cross-reference chain: any domain System Log record can be traced back to the exact system-layer version that was operational at that moment, without coupling the system log and domain CTLs structurally.

```
Domain System Log TraceEvent.metadata.system_physics_hash
  └─► System System Log CommitmentRecord.subject_hash  (system_physics_activation)
        └─► cfg/system-physics.json  (compiled, SHA-256 verified)
              └─► cfg/system-physics.yaml  (YAML source, human-authored)
```

### 2.4 Novel Synthesis Telemetry

Every domain/session `TraceEvent` record **SHOULD** include `model_id` and `model_version` in its `metadata` block — the identifier and version of the LLM model used for the turn. These fields are passed per-request via `ChatRequest.model_id` and `ChatRequest.model_version`.

When a domain physics invariant with a `signal_type` field fires (fails), the orchestrator **MUST** propagate the `signal_type` value into the TraceEvent metadata as `novel_synthesis_signal`. This enables system-level tracking of novel synthesis events across domains without coupling the system to domain-specific invariant logic.

Resolution of novel synthesis events uses a **two-key verification gate**:

1. **Key 1 (LLM/Domain):** The domain invariant fires and the orchestrator propagates the signal. This is automatic.
2. **Key 2 (Human-in-the-Loop):** The Domain Authority reviews the escalation and issues a CommitmentRecord with `commitment_type` of either `novel_synthesis_verified` or `novel_synthesis_rejected`. When issuing `novel_synthesis_rejected`, the CommitmentRecord `metadata` **MUST** include a `denial_rationale` object with `reason_category` (enum) and `authority_note` (string ≤ 512 chars) \u2014 see `commitment-record-schema` for the full field contract.

The system **MUST NOT** record a novel synthesis as validated until Key 2 has been turned. Escalation records for novel synthesis review **SHOULD** use `trigger_type: novel_synthesis_review`.

See [`novel-synthesis-framework(7)`](../docs/7-concepts/novel-synthesis-framework.md) for the full architectural description.

---

## 3. System Logs Conformance

Every Lumina system must maintain a System Log-conformant ledger. Requirements:

- **Append-only**: records may not be modified or deleted
- **Hash-chained**: each record includes the hash of the previous record
- **No transcripts**: records must not contain raw conversation content
- **Pseudonymous**: actor identifiers are pseudonymous; real-identity mapping is held externally
- **Record types**: all systems must support `CommitmentRecord` and `TraceEvent` at minimum
- **Policy commitment gate**: active module `domain-physics.json` hash must match a committed `CommitmentRecord` before autonomous session execution
- **Provenance metadata**: turn traces should include policy/prompt and payload lineage hashes (`domain_physics_hash`, `system_prompt_hash`, `turn_data_hash`, `prompt_contract_hash`, `tool_results_hash`, `llm_payload_hash`, `response_hash`)

See [`system-log-v1.md`](system-log-v1.md) for the full System Log specification.

---

## 4. Compressed State Conformance

For domains that implement subject state tracking, each domain pack defines its own **subject state schema** in its `schemas/` directory. The D.S.A. engine is agnostic to the specific fields; domain libs populate whatever fields the domain schema defines.

A domain's subject state schema must conform to the following structural requirements:

- Stored as a versioned JSON Schema file in `domain-pack/schemas/`
- Fields must be numeric (float or integer) or simple structured objects — no free text
- All fields must be populated by deterministic domain-lib logic (see [`domain-state-lib-contract-v1.md`](domain-state-lib-contract-v1.md))
- Schema changes that add required fields or alter field semantics require a version bump

> **Education domain example:** The education domain's compressed learner state schema is at [`../domain-packs/education/schemas/compressed-state-schema-v1.json`](../domain-packs/education/schemas/compressed-state-schema-v1.json). It includes affect (SVA), per-skill mastery, challenge, uncertainty, and operating-band thresholds — all concepts specific to educational assessment.

See [`domain-state-lib-contract-v1.md`](domain-state-lib-contract-v1.md) for the domain-lib contract that populates the state.

---

## 5. Naming and Terminology

All Project Lumina documents and code must use the following canonical terminology:

| Canonical Term | Description | Do NOT use |
|----------------|-------------|------------|
| **Project Lumina** | The overall system | "Spotter" |
| **System Logs** | The append-only accountability ledger | "Flight Data Recorder", "FDR" |
| **Domain Authority** | The human expert who authors the domain | "Master" |
| **D.S.A. Framework** | Domain, State, Action | Other acronyms |
| **Meta Authority** | Domain Authority one level above | "Super-admin" |
| **Domain Physics** | The authored ruleset (YAML) | "Rules file" |
| **Standing Order** | A bounded automated response | "Auto-response", "rule" |

---

## 6. RAG Layer Conformance

Systems using retrieval-augmented generation must conform to the grounding contract:

- Cite retrieved artifacts by ID and version in every response that uses retrieved content
- If required context cannot be retrieved, escalate rather than hallucinate
- Retrieval scope is bounded by the current Domain Physics — do not retrieve beyond authorized scope
- No retrieval of PII beyond what is declared in the domain's subject profile schema

See [`../retrieval/rag-contracts.md`](../retrieval/rag-contracts.md) for the full RAG contract.

---

## 7. Versioning

This meta-specification itself is versioned. Breaking changes to this specification:
- Increment the major version
- All conformant domain packs must declare the lumina-core version they target
- A domain pack targeting `lumina-core-v1` is not required to change until `lumina-core-v2` is released

---

## 8. Conformance Checklist

Before publishing a domain pack or implementation:

**System Layer**
- [ ] `cfg/system-physics.yaml` validates against `system-physics-schema-v1.json`
- [ ] `cfg/system-physics.json` (compiled form) is present and its SHA-256 matches a `CommitmentRecord (system_physics_activation)` in the system log
- [ ] `specs/global-system-prompt-v1.md` reflects the current `ci_output_contract` in `cfg/system-physics.yaml`
- [ ] System Log is append-only and hash-chained
- [ ] Domain/session `TraceEvent` records include `system_physics_hash` in `metadata`

**Domain Packs**
- [ ] Domain Physics YAML validates against `domain-physics-schema-v1.json`
- [ ] At least one `critical` invariant is defined
- [ ] All standing orders have `max_attempts` and `escalation_on_exhaust` set
- [ ] Subject profile template validates against the domain pack's subject profile schema (in `schemas/`)
- [ ] CHANGELOG.md is present and up to date
- [ ] System Log integration is append-only and hash-chained
- [ ] No transcript content is stored in the System Logs
- [ ] All identifiers are pseudonymous
- [ ] Terminology conforms to Section 5
- [ ] If the domain is human-facing (`requires_consent: true`), a consent record is required before the session begins
- [ ] If module domain-lib subsystems are used, module `domain-physics` declares the relevant `subsystem_configs` block(s) with required thresholds
- [ ] Module `domain-physics` owns normative thresholds/tolerances and standing-order trigger semantics
- [ ] Every declared `tool_adapters` ID resolves to an existing tool adapter contract file
- [ ] Material module policy updates include version bump, YAML->JSON regeneration, and System Log hash commitment before activation
- [ ] `docs/` directory contains required sections (`1-commands/`, `3-functions/`, `7-concepts/`) with `README.md` in each
- [ ] Domain doc files are tracked in `docs/MANIFEST.yaml` and pass integrity check

---

*This specification is maintained by the Project Lumina governance body. All changes require a Major version bump.*
