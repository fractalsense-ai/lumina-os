---
version: 1.0.0
last_updated: 2026-03-20
---

# list-domains(1)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-20  

---

## NAME

`list-domains` — List all registered domains in the Lumina domain registry

## SYNOPSIS

```
POST /api/admin/command
{ "instruction": "list domains" }
```

Or via the system domain chat interface:

```
> list domains
```

## DESCRIPTION

Queries the domain registry (`cfg/domain-registry.yaml`) and returns all
registered domains with their metadata (domain_id, label, module_prefix,
runtime config path).

This operation is **HITL-exempt** — it executes immediately without staging
or approval.  No System Log record is written for read-only queries.

## RBAC

Requires one of: `root`, `domain_authority`, `it_support`.

## RESPONSE

```json
{
  "staged_id": null,
  "hitl_exempt": true,
  "result": {
    "operation": "list_domains",
    "domains": [
      {
        "domain_id": "education",
        "label": "Education",
        "module_prefix": "edu",
        "runtime_config_path": "domain-packs/education/cfg/runtime-config.yaml"
      }
    ],
    "count": 3
  }
}
```

## SEE ALSO

list-modules(1), domain-registry-schema-v1(4), rbac-spec-v1(5)
