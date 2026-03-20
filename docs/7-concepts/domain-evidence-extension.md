---
version: 1.0.0
last_updated: 2026-03-20
---

# Domain Evidence Extension

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-15

---

## What Is Domain Evidence?

Every Project Lumina session produces per-turn **evidence** — structured signals that describe what happened in a turn without quoting transcript content. This evidence is recorded in the `evidence_summary` field of a System Log `TraceEvent`.

Because Lumina hosts radically different domains — algebra tutoring, agricultural operations, corporate training, medical continuing education — no single set of field names can describe every domain's signals. A hint request means nothing to a soil sensor domain. An out-of-tolerance reading means nothing to an algebra tutor.

The **Domain Evidence Extension** is the mechanism that lets each domain pack own and declare its diagnostic vocabulary while still contributing to a shared, auditable ledger.

---

## The Standard Envelope

All `evidence_summary` objects share a flat structure with:

1. **Reserved system keys** (underscore-prefixed, managed by the core system)
2. **Universal base fields** (expected from all domains, regardless of context)
3. **Domain-specific fields** (declared by each domain in its `evidence-schema.json`)

```json
{
  "_domain":             "domain/lumina/education/v1",
  "_schema_version":     "1.0",
  "response_latency_sec": 8.4,
  "off_task_ratio":       0.0,
  "correctness":         "partial",
  "hint_used":           false,
  "frustration_marker_count": 1
}
```

### Reserved Keys

| Key | Description |
|-----|-------------|
| `_domain` | The `id` of the domain-physics module that produced this record |
| `_schema_version` | Version of the domain's `evidence-schema.json` at the time of the event |

Reserved keys allow audit tooling to identify which domain evidence schema to validate a record against, even if the parent `TraceEvent` context is unavailable.

### Universal Base Fields

| Field | Type | Description |
|-------|------|-------------|
| `response_latency_sec` | `number \| null` | Seconds from when the previous response was fully delivered to when the student's reply was received by the server. Captured at request arrival, before any server-side LLM or SLM processing, so it reflects student-paced response time only. |
| `off_task_ratio` | `number \| null` | Fraction of response not engaging the current task (0.0–1.0) |

These fields are expected from all domains. They are observable without domain semantics and enable cross-domain analytics (e.g. comparing engagement patterns across departments or cohorts).

---

## How Domains Declare Their Evidence Vocabulary

### 1. Create `evidence-schema.json`

Place an `evidence-schema.json` file in the module directory alongside `domain-physics.yaml`:

```
domain-packs/
  my-domain/
    modules/
      my-module/
        domain-physics.yaml
        domain-physics.json
        evidence-schema.json    ← new
```

The file declares which domain-specific fields `evidence_summary` objects from this module will contain, along with their types and descriptions. It must conform to [`standards/domain-evidence-schema-v1.json`](../../standards/domain-evidence-schema-v1.json).

Minimal example:

```json
{
  "schema_id": "lumina:evidence:my-domain:v1",
  "version": "1.0",
  "domain_id": "domain/org/my-domain/v1",
  "description": "Evidence vocabulary for My Domain.",
  "fields": {
    "accuracy_score": {
      "type": ["number", "null"],
      "minimum": 0,
      "maximum": 1,
      "description": "Normalised accuracy of the subject's response."
    },
    "procedure_followed": {
      "type": ["boolean", "null"],
      "description": "True if the subject followed the required procedure."
    }
  }
}
```

Field names must be lowercase `snake_case` and must not start with `_`.

### 2. Register It in `domain-physics.yaml`

Add the `evidence_schema` block to your `domain-physics.yaml`:

```yaml
evidence_schema:
  path: "evidence-schema.json"
  version: "1.0"
```

The `version` must match the `version` field declared in `evidence-schema.json`.

### 3. Update MANIFEST.yaml

Add an entry in `docs/MANIFEST.yaml` for the new `evidence-schema.json` file.

---

## Validation Layers

| Layer | What it enforces |
|-------|-----------------|
| **System Log JSON Schema** (`ledger/trace-event-schema.json`) | `evidence_summary` is an object or null. `_domain` and `_schema_version`, when present, are strings. All other fields are open. |
| **Domain-physics schema** | `evidence_schema.path` and `evidence_schema.version` are correctly typed. |
| **Evidence meta-schema** (`standards/domain-evidence-schema-v1.json`) | The `evidence-schema.json` file itself is structurally valid. |
| **Runtime** | Not enforced. Field-level validation against declared schemas is optional and audit-time only. |

This layered approach means no domain is blocked by schema evolution in another domain, and the core ledger stays domain-agnostic.

---

## Existing Domain Evidence Schemas

| Domain | Schema ID | File |
|--------|-----------|------|
| Education — Algebra Level 1 | `lumina:evidence:education:v1` | `domain-packs/education/modules/algebra-level-1/evidence-schema.json` |
| Agriculture — Operations Level 1 | `lumina:evidence:agriculture:v1` | `domain-packs/agriculture/modules/operations-level-1/evidence-schema.json` |

---

## Related

- [`standards/domain-evidence-extension-v1.md`](../../standards/domain-evidence-extension-v1.md) — Normative standard
- [`standards/domain-evidence-schema-v1.json`](../../standards/domain-evidence-schema-v1.json) — Meta-schema for evidence declarations
- [`standards/system-log-v1.md`](../../standards/system-log-v1.md) — System Log specification
- [`ledger/trace-event-schema.json`](../../ledger/trace-event-schema.json) — TraceEvent JSON Schema
