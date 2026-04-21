---
version: 1.0.0
last_updated: 2026-03-25
---

# list-commands(1)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-25  

---

## NAME

`list-commands` — List all available admin commands with metadata

## SYNOPSIS

```
POST /api/admin/command
{ "instruction": "list commands" }
```

Or via the system domain chat interface:

```
> list commands
```

## DESCRIPTION

Returns a catalog of every registered admin operation with its
description, HITL-exempt status, and minimum required role.

This operation is **HITL-exempt** — it executes immediately without staging
or approval.  No System Log record is written for read-only queries.

## PARAMETERS

| Parameter         | Type    | Default | Description                                   |
|-------------------|---------|---------|-----------------------------------------------|
| `include_details` | boolean | `true`  | Include description, HITL status, and min_role |

## RBAC

Requires one of: `root`, `admin`, `super_admin`.

## RESPONSE

```json
{
  "staged_id": null,
  "hitl_exempt": true,
  "result": {
    "operation": "list_commands",
    "commands": [
      {
        "name": "commit_domain_physics",
        "description": "Commit the current domain-physics hash ...",
        "hitl_exempt": false,
        "min_role": "admin"
      }
    ],
    "count": 21
  }
}
```

When `include_details` is `false`, each entry contains only `name`.

## SEE ALSO

- [list-domains](list-domains.md)
- [list-modules](list-modules.md)
- `standards/admin-command-schemas/list-commands.json`
