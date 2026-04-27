---
version: 1.0.0
last_updated: 2026-03-20
---

# File Generation & Staging

> **Architecture layer**: Tier 3 — Execution (actuator isolation)
>
> **Principle**: No LLM touches the filesystem directly.

## Overview

The File Generation & Staging subsystem enforces a strict three-phase
pipeline for any file that an LLM wants to create or modify:

```
  Brain (LLM)           Checkpoint (Staging)          Actuator (Writer)
  ───────────           ────────────────────          ─────────────────
  Generates JSON   →    Validated & staged as    →    Deterministic write
  payload                pending envelope              from template
                         in data/staging/               to final path
                                │
                         Human review (DA/root)
                                │
                         Approve / Reject
```

### Why?

1. **Safety** — LLM hallucinations never reach the filesystem.
2. **Auditability** — Every file operation has a System Log commitment record.
3. **Reversibility** — Rejected files stay in staging for investigation.
4. **Consistency** — Templates enforce structural invariants that the LLM
   cannot violate.

## Components

### StagingService (`src/lumina/staging/staging_service.py`)

Central orchestrator for the stage → review → write lifecycle.

| Method | Description |
|--------|-------------|
| `stage_file(payload, template_id, actor_id)` | Validates payload against template requirements, writes JSON envelope to `data/staging/{uuid}.json`, creates System Log `hitl_command_staged` record. |
| `list_staged(actor_id=None)` | Lists all pending envelopes (optionally filtered by actor). |
| `get_staged(staged_id)` | Loads a single envelope by UUID. |
| `approve_staged(staged_id, approver_id, target_overrides)` | Writes the file to its final path via `write_from_template`, creates System Log `hitl_command_accepted` record. |
| `reject_staged(staged_id, approver_id, reason)` | Marks envelope as rejected, creates System Log `hitl_command_rejected` record. |

### TemplateRegistry (`src/lumina/staging/template_registry.py`)

Immutable registry mapping `template_id` → `Template` descriptors.

| Template ID | Description | Target Pattern |
|-------------|-------------|----------------|
| `domain-physics` | Domain physics JSON | `model-packs/{domain_short}/cfg/domain-physics.json` |
| `evidence-schema` | Evidence schema JSON | `model-packs/{domain_short}/cfg/evidence-schema.json` |
| `tool-adapter` | Tool adapter YAML | `model-packs/{domain_short}/modules/{module}/tool-adapters/{adapter_name}-adapter-v{major}.yaml` |
| `student-profile` | Student/entity profile | `model-packs/{domain_short}/profiles/{profile_id}.yaml` |
| `context-hint` | Daemon batch context hint | `model-packs/{domain_short}/context-hints/{hint_id}.json` |

Each template defines:
- **required_fields** — Fields that must appear in the payload.
- **default_structure** — Skeleton dict merged with the payload (payload wins).
- **target_pattern** — String pattern with `{placeholders}` for the final path.
- **file_format** — `"json"` or `"yaml"`.

### FileWriter (`src/lumina/staging/file_writer.py`)

Deterministic actuator: merges validated payload into template defaults and
writes atomically (temp file → `os.replace`).  Never calls an LLM.

## Staging Envelope

Each staged file is persisted as a JSON envelope:

```json
{
  "staged_id": "uuid-v4",
  "template_id": "domain-physics",
  "actor_id": "user-pseudonymous-id",
  "actor_role": "admin",
  "payload": { ... },
  "staged_at": "2026-03-20T04:00:00+00:00",
  "approval_status": "pending",
  "approver_id": null,
  "resolved_at": null,
  "final_path": null,
  "log_record_id": "uuid"
}
```

Schema: `standards/staged-file-schema-v1.json`

## API Endpoints

| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| POST | `/api/staging/create` | root, admin | Stage a new file |
| GET | `/api/staging/pending` | root, admin, operator | List pending files |
| GET | `/api/staging/{staged_id}` | root, admin, operator | Get one staged file |
| POST | `/api/staging/{staged_id}/approve` | root, admin | Approve and write |
| POST | `/api/staging/{staged_id}/reject` | root, admin | Reject staged file |

## System Log Integration

Every state transition produces a System Log `CommitmentRecord`:

| Transition | commitment_type |
|------------|-----------------|
| File staged | `hitl_command_staged` |
| File approved | `hitl_command_accepted` |
| File rejected | `hitl_command_rejected` |

## Adding a New Template

1. Define a `Template(...)` in `template_registry.py` with `_register()`.
2. Ensure the corresponding JSON Schema exists in `standards/`.
3. Update this document's template table.

## Related

- [Inspection Middleware](inspection-middleware.md) — validates payloads before staging.
- [Admin Command Schemas](../8-admin/admin-command-schemas.md) — Default Deny for admin operations.
- [Adapter Naming Convention](../5-standards/adapter-naming-convention.md) — naming for tool-adapter templates.
