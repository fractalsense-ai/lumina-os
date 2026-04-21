---
version: 1.0.0
last_updated: 2026-03-20
---

# Admin Command Schemas — Default Deny

## Overview

Every admin command that the SLM parses from natural language must match a
**pre-approved JSON Schema** before it can be staged for human-in-the-loop
(HITL) resolution.  Commands that lack a registered schema — or whose
parameters violate their schema — are **rejected at parse time**, never
reaching the staging queue.

This is the "Default Deny" pillar of the Lumina security model.

## Location

Schema files live in `standards/admin-command-schemas/`, one per operation.
The **Command Schema Registry** (`src/lumina/middleware/command_schema_registry.py`)
loads them on first use and exposes:

```python
from lumina.middleware.command_schema_registry import validate_command

approved, violations = validate_command("update_user_role", {"user_id": "alice", "new_role": "operator"})
```

## Integration Point

The validation gate sits in two places inside `src/lumina/api/routes/admin.py`:

1. **Stage path** (`POST /api/admin/command`) — after the SLM parser returns
   `{operation, target, params}` and the operation is confirmed as known, the
   params are validated against the schema.  Failures produce a `422`.

2. **Modify path** (`POST /api/admin/command/{staged_id}/resolve` with
   `action: "modify"`) — the replacement command must also pass schema
   validation before acceptance.

## Schema Structure

Every schema is a JSON Schema (Draft 2020-12) file with the following shape:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "lumina://standards/admin-command-schemas/<operation>.json",
  "title": "<operation_name>",
  "description": "...",
  "type": "object",
  "required": ["operation", "params"],
  "additionalProperties": false,
  "properties": {
    "operation": { "const": "<operation_name>" },
    "target": { "type": "string" },
    "params": {
      "type": "object",
      "required": [...],
      "additionalProperties": false,
      "properties": { ... }
    }
  }
}
```

Key invariants:
- `additionalProperties: false` at both the top level and inside `params`.
- `operation` is a `const` — each schema locks to exactly one operation name.
- `target` is always optional (string).

## Registered Operations

| Operation | Required Params | Role(s) |
|---|---|---|
| `update_domain_physics` | `domain_id`, `updates` | `root`, `admin` |
| `commit_domain_physics` | `domain_id` | `root`, `admin` |
| `update_user_role` | `user_id`, `new_role` | `root` |
| `deactivate_user` | `user_id` | `root` |
| `assign_domain_role` | `user_id`, `module_id`, `domain_role` | `root`, `admin` |
| `revoke_domain_role` | `user_id`, `module_id` | `root`, `admin` |
| `resolve_escalation` | `escalation_id`, `resolution`, `rationale` | `root`, `admin` |
| `review_ingestion` | `ingestion_id` | `root`, `admin` |
| `approve_interpretation` | `ingestion_id`, `interpretation_id` | `root`, `admin` |
| `reject_ingestion` | `ingestion_id`, `reason` | `root`, `admin` |
| `trigger_daemon_task` | *(none)* | `root`, `admin` |
| `review_proposals` | *(none)* | `root`, `admin` |
| `invite_user` | `username`, `role` | `root` |
| `list_escalations` | *(none)* | `root`, `admin`, `super_admin` |
| `list_ingestions` | *(none)* | `root`, `admin`, `super_admin` |
| `module_status` | `domain_id` | `root`, `admin`, `super_admin` |
| `explain_reasoning` | `event_id` | `root`, `admin`, `operator`, `half_operator` |
| `daemon_status` | *(none)* | `root`, `admin`, `super_admin` |
| `list_domain_rbac_roles` | `domain_id` | `root`, `admin`, `super_admin` |
| `get_domain_module_manifest` | `domain_id` | `root`, `admin`, `super_admin` |

## Adding a New Operation

1. Create `standards/admin-command-schemas/<operation-name>.json` following the structure above.
2. Add the operation string to `_KNOWN_OPERATIONS` in `src/lumina/api/routes/admin.py`.
3. Add a handler branch in `_execute_admin_operation()` in the same file.
4. Add the operation to `ADMIN_OPERATIONS` in `src/lumina/core/slm.py` so the SLM can parse it.
5. The registry will auto-discover the new schema file on next reload.

## Files

| File | Purpose |
|---|---|
| `standards/admin-command-schemas/*.json` | Per-operation JSON Schema definitions |
| `src/lumina/middleware/command_schema_registry.py` | Registry loader and `validate_command()` |
| `src/lumina/api/routes/admin.py` | HITL staging with schema validation gate |
| `src/lumina/core/slm.py` | SLM parser (`slm_parse_admin_command()`) |
| `tests/test_command_schema_registry.py` | Unit tests for the registry |
