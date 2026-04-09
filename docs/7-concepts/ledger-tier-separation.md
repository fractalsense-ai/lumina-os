---
version: 1.0.0
last_updated: 2026-03-23
---

# Ledger Tier Separation

> *3-tier HMVC-correct ledger architecture for the System Log.*

## Overview

The System Log uses a **three-tier directory layout** that mirrors Lumina's
HMVC hierarchy.  Every log record is written to exactly one tier based on its
scope.  This eliminates the earlier flat-file anti-pattern where system-level
auth events, domain-pack telemetry, and per-module records all funnelled into
a single ``session-admin-_admin.jsonl`` file.

## Tiers

| Tier     | Path template                                       | Typical contents                       |
|----------|-----------------------------------------------------|----------------------------------------|
| System   | ``system/session-{session_id}.jsonl``               | Auth, HITL, nightcycle, audit traces   |
| Domain   | ``domains/{domain_id}/domain.jsonl``                | Domain-pack activation, domain roles   |
| Module   | ``domains/{domain_id}/modules/{module_id}.jsonl``   | Student assignments, module evidence   |

### Directory layout (example)

```
<log-root>/
├── system/
│   ├── session-admin.jsonl
│   └── session-abc123.jsonl
└── domains/
    └── edu/
        ├── domain.jsonl
        └── modules/
            ├── algebra-level-1.jsonl
            └── geometry-intro.jsonl
```

## Routing rules

Record classification follows these rules, evaluated top-to-bottom:

1. **CommitmentRecords** with ``commitment_type`` in the system set
   (``user_registered``, ``role_change``, ``token_revoked``, …) → **system**.
2. **TraceEvents** with ``event_type`` in the system set
   (``routing_decision``, ``admin_cmd_trace``, …) → **system**.
3. **EscalationRecords** → **system**.
4. **CommitmentRecords** with ``commitment_type`` in the domain set
   (``domain_pack_activation``, ``domain_role_assignment``, …) → **domain**.
5. **Records with an explicit ``domain_id`` or ``domain_pack_id``** that
   did not match an earlier rule → **domain**.
6. **Everything else** → **system** (safe fallback).

For the canonical list of type sets, see ``scripts/migrate-ledger-tiers.py``.

## ScopedPersistenceAdapter

Domain-pack handler code runs inside a ``ScopedPersistenceAdapter`` which
wraps the real persistence backend with a fixed ``domain_id``.

| Method                    | Behaviour                                              |
|---------------------------|--------------------------------------------------------|
| ``append_log_record()``   | Auto-routes to the **domain** or **module** tier       |
| ``append_system_log_record()`` | Raises ``PermissionError`` — domain packs may not write system-tier records |
| All other methods         | Proxied unchanged to the inner adapter                 |

This enforces the HMVC boundary at write time: a domain pack physically
cannot pollute the system ledger.

## Hash chain integrity

Each ledger file maintains its own independent SHA-256 hash chain.  The first
record in a file uses ``prev_record_hash: "genesis"``.  When records are
migrated from the legacy flat layout the chain is recomputed per target file.

## Migration

Run ``scripts/migrate-ledger-tiers.py`` to classify and copy legacy flat
ledger records into the new tier directories.  The script is idempotent and
does **not** delete the original files.

```powershell
python scripts/migrate-ledger-tiers.py --log-dir ./data/logs
# or dry-run first:
python scripts/migrate-ledger-tiers.py --log-dir ./data/logs --dry-run
```

## Related

* [HMVC Heritage](hmvc-heritage.md) — architecture mapping
* [System Log Micro-Router](system-log-micro-router.md) — severity-based routing
* [system-log-schema-v1.json](../../standards/system-log-schema-v1.json) — record schema
