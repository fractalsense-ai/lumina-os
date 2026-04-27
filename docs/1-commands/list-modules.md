---
version: 1.0.0
last_updated: 2026-03-20
---

# list-modules(1)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-20  

---

## NAME

`list-modules` — List all modules registered under a specific domain

## SYNOPSIS

```
POST /api/admin/command
{ "instruction": "list modules for education" }
```

Or via the system domain chat interface:

```
> list modules for education
```

## DESCRIPTION

Queries the domain registry and runtime configuration for a given domain,
returning all module IDs and their `domain-physics.json` paths.

Modules are discovered from the domain's `runtime-config.yaml`:

1. All entries under `module_map` are enumerated.
2. The default module is read from the domain-physics.json `id` field.

This operation is **HITL-exempt** — it executes immediately without staging
or approval.

## PARAMETERS

| Parameter    | Required | Description                              |
|-------------|----------|------------------------------------------|
| `domain_id` | Yes      | Domain identifier (e.g. `education`)     |

## RBAC

Requires one of: `root`, `admin`, `super_admin`.

A `admin` can only list modules for domains they govern.

## RESPONSE

```json
{
  "staged_id": null,
  "hitl_exempt": true,
  "result": {
    "operation": "list_modules",
    "domain_id": "education",
    "modules": [
      {
        "module_id": "domain/edu/pre-algebra/v1",
        "domain_physics_path": "model-packs/education/modules/pre-algebra/domain-physics.json"
      },
      {
        "module_id": "domain/edu/algebra-intro/v1",
        "domain_physics_path": "model-packs/education/modules/algebra-intro/domain-physics.json"
      }
    ],
    "count": 4
  }
}
```

## ERRORS

| Code | Condition                                    |
|------|---------------------------------------------|
| 400  | `domain_id` does not match any domain       |
| 403  | DA not authorized for the requested domain  |
| 422  | `domain_id` parameter missing               |

## SEE ALSO

list-domains(1), domain-registry-schema-v1(4), rbac-spec-v1(5)
