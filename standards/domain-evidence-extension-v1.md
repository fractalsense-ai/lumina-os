# Domain Evidence Extension — V1

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-15

---

## Purpose

This document is the normative standard for the Project Lumina **Domain Evidence Extension** mechanism. It defines:

1. The standard `evidence_summary` envelope format used in all System Log `TraceEvent` and `EscalationRecord` records.
2. The **universal base fields** that all domain modules are expected to emit.
3. How domain modules declare their own evidence field vocabulary in an `evidence-schema.json` file.
4. The validation contract — what is enforced at the schema layer vs. left to domain-level tooling.

This standard governs the `evidence_summary` field described in [`standards/system-log-v1.md`](system-log-v1.md). The JSON Meta-Schema that `evidence-schema.json` files must conform to is [`standards/domain-evidence-schema-v1.json`](domain-evidence-schema-v1.json).

---

## Design Principle

The System Logs does not own domain vocabulary. The System Logs defines the **container**: a typed, append-only record with a standard envelope. Each domain module owns the **contents**: the set of structured fields that describe a turn in that domain's language.

This allows any domain to extend `evidence_summary` freely, while guaranteeing:
- A discoverable reference to the schema that validates the contents.
- A stable, cross-domain baseline of universal signals.
- No education-specific fields in the core ledger specification.

---

## Standard Envelope

Every `evidence_summary` object uses a **flat structure** with the following layout:

```
{
  "_domain":         "<domain_id>",      // reserved — string
  "_schema_version": "<semver>",         // reserved — string
  "response_latency_sec": <float|null>,  // universal base
  "off_task_ratio":       <float|null>,  // universal base
  // domain-specific fields follow:
  ...
}
```

### Reserved Keys

Keys beginning with `_` (underscore) are reserved by the System Logs system. Domain fields MUST NOT use underscore-prefixed names.

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `_domain` | string | Recommended | The `id` of the domain-physics module that produced this record. Matches `domain_pack_id` on the parent `TraceEvent`. |
| `_schema_version` | string (semver) | Recommended | Version of the domain's `evidence-schema.json` in effect when this record was created. Enables audit tooling to validate records against the correct schema version. |

> **Note:** `_domain` and `_schema_version` are recommended for all new records and required for records that will be validated against a domain evidence schema. Existing records without these keys remain valid — the System Log JSON Schema accepts any object for `evidence_summary`.

### Universal Base Fields

These two fields are expected from all domain modules. They measure observable turn-level signals independent of domain semantics.

| Field | Type | Description |
|-------|------|-------------|
| `response_latency_sec` | `number \| null` | Wall-clock seconds from prompt delivery to response receipt. |
| `off_task_ratio` | `number \| null` | Fraction of the response not engaging with the current task. 0.0 = fully on-task, 1.0 = fully off-task. Must be in `[0.0, 1.0]`. |

Domain modules that cannot meaningfully measure a universal base field SHOULD emit `null` rather than omitting the key.

---

## Declaring Domain Evidence Fields

Each domain module that emits domain-specific evidence fields declares them in an `evidence-schema.json` file located alongside its `domain-physics.yaml` / `domain-physics.json`. The `domain-physics` file references it via the `evidence_schema` block:

```yaml
# in domain-physics.yaml
evidence_schema:
  path: "evidence-schema.json"   # relative to this file's directory
  version: "1.0"                 # must match the version in evidence-schema.json
```

### `evidence-schema.json` Format

The file must conform to [`standards/domain-evidence-schema-v1.json`](domain-evidence-schema-v1.json).

Minimal structure:

```json
{
  "schema_id": "lumina:evidence:<domain-name>:v<major>",
  "version": "<major.minor>",
  "domain_id": "<domain-physics-id>",
  "description": "...",
  "fields": {
    "<field_name>": {
      "type": "<json-schema-type>",
      "description": "..."
    }
  }
}
```

Field definitions use standard JSON Schema keywords (`type`, `enum`, `minimum`, `maximum`, `description`). Field names must be lowercase `snake_case` and must not start with `_`.

---

## Education Domain Example

**Schema ID:** `lumina:evidence:education:v1`

**File:** `domain-packs/education/modules/algebra-level-1/evidence-schema.json`

| Field | Type | Description |
|-------|------|-------------|
| `correctness` | `"correct" \| "incorrect" \| "partial" \| null` | Whether the answer is correct |
| `hint_used` | `boolean \| null` | Subject explicitly requested a hint |
| `frustration_marker_count` | `integer \| null` | Count of frustration signals in the message |
| `repeated_error` | `boolean \| null` | Same error type made in consecutive turns |
| `step_count` | `integer \| null` | Algebraic steps shown |
| `min_steps` | `integer \| null` | Minimum steps required (from curriculum) |
| `solution_value` | `number \| string \| null` | Extracted solution value |
| `equivalence_preserved` | `boolean \| null` | Each step preserves algebraic equivalence |

A complete education `evidence_summary` record looks like:

```json
{
  "_domain": "domain/lumina/education/v1",
  "_schema_version": "1.0",
  "response_latency_sec": 8.4,
  "off_task_ratio": 0.0,
  "correctness": "partial",
  "hint_used": false,
  "frustration_marker_count": 1,
  "repeated_error": false,
  "step_count": 2,
  "min_steps": 3,
  "solution_value": 5,
  "equivalence_preserved": true
}
```

---

## Agriculture Domain Example

**Schema ID:** `lumina:evidence:agriculture:v1`

**File:** `domain-packs/agriculture/modules/operations-level-1/evidence-schema.json`

| Field | Type | Description |
|-------|------|-------------|
| `within_tolerance` | `boolean \| null` | Sensor reading or decision within acceptable range |
| `step_count` | `integer \| null` | Discrete operational steps provided |

A complete agriculture `evidence_summary` record:

```json
{
  "_domain": "domain/lumina/agriculture/v1",
  "_schema_version": "1.0",
  "response_latency_sec": 3.1,
  "off_task_ratio": 0.0,
  "within_tolerance": true,
  "step_count": 1
}
```

---

## Validation Contract

| Layer | What is enforced |
|-------|-----------------|
| **System Log JSON Schema** (`ledger/trace-event-schema.json`) | `evidence_summary` is an object or null. `_domain` and `_schema_version`, when present, are strings. All other fields are pass-through (`additionalProperties: true`). |
| **Domain-physics schema** (`standards/domain-physics-schema-v1.json`) | `evidence_schema.path` and `evidence_schema.version` are present and correctly typed when `evidence_schema` is declared. |
| **Domain evidence meta-schema** (`standards/domain-evidence-schema-v1.json`) | The domain's `evidence-schema.json` itself is structurally valid (required keys, no underscore-prefixed field names). |
| **Runtime / audit tooling** | Optional. The System Log validator does not enforce field-level evidence validation at runtime. Domain evidence schemas are available for offline audit validation, enabling post-hoc verification that emitted fields match declared vocabulary. |

---

## Adding a New Domain

To extend the System Logs with a new domain's evidence vocabulary:

1. Create `<domain-pack-root>/<module>/<evidence-schema.json>` conforming to `standards/domain-evidence-schema-v1.json`.
2. Add the `evidence_schema` block to the module's `domain-physics.yaml`:
   ```yaml
   evidence_schema:
     path: "evidence-schema.json"
     version: "1.0"
   ```
3. In the domain's runtime adapter, ensure `evidence_summary` objects include `_domain` and `_schema_version` envelope keys.
4. Update `docs/MANIFEST.yaml` to register the new `evidence-schema.json`.

---

## Related

- [`standards/system-log-v1.md`](system-log-v1.md) — System Log specification
- [`standards/domain-evidence-schema-v1.json`](domain-evidence-schema-v1.json) — Meta-schema for evidence declarations
- [`ledger/trace-event-schema.json`](../ledger/trace-event-schema.json) — TraceEvent JSON Schema
- [`standards/domain-physics-schema-v1.json`](domain-physics-schema-v1.json) — Domain physics schema
