---
version: 1.0.0
last_updated: 2026-03-20
---

# system-domain-operations

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-03-16  

---

Operational reference for the Project Lumina system domain: both the machine-readable
policy layer (`cfg/system-physics.yaml`) that governs the Conversational Interface
across all domains, and the live system domain pack (`domain-packs/system/`) that
provides an administration session interface for `root` and `it_support` users.

---

## A — System domain overview

The **system domain** is a full named domain pack located at `domain-packs/system/`.
It is the default routing destination for `root` and `it_support` users when no
explicit `domain_id` is provided and NLP routing does not confidently match another
domain (see `cfg/domain-registry.yaml` → `role_defaults`).

| Component | Path | Role |
|-----------|------|------|
| System physics source | `cfg/system-physics.yaml` | Human-editable global policy source |
| System physics compiled | `cfg/system-physics.json` | Runtime-loaded, schema-validated |
| System physics schema | `standards/system-physics-schema-v1.json` | JSON Schema for CI layer |
| Domain registry entry | `cfg/domain-registry.yaml` → `system:` | Routing + live session config |
| Domain pack runtime config | `domain-packs/system/cfg/runtime-config.yaml` | Full live-session config |
| Domain physics | `domain-packs/system/modules/system-core/domain-physics.json` | Glossary, permissions, topics |
| Domain prompts | `domain-packs/system/prompts/` | LLM persona + turn interpretation |
| Runtime adapters | `domain-packs/system/controllers/runtime_adapters.py` | Minimal state/step/interpreter |
| Deprecated stub | `cfg/system-runtime-config.yaml` | Superseded; retained for reference only |
| System lib | `src/lumina/lib/system_health.py` | Passive state estimator (hw probes) |
| Hardware probes | `src/lumina/systools/hw_disk.py` · `hw_temp.py` · `hw_memory.py` | Passive, lib-invoked only |

### Access control

Session execution in the system domain is restricted to principals with `root` or
`it_support` roles.  The domain-physics permission block uses mode `"770"` — owner
and group have full rwx, all others have no access.

`qa`, `auditor`, `domain_authority`, and `user` principals that attempt a session
in the system domain receive `403 Module access denied`.  They may still see the
`system` domain listed in `/api/domains` because it is a registered registry entry,
but they cannot execute sessions.

### Role-based default routing

`root` and `it_support` users who send a chat message with no `domain_id` and whose
message does not confidently match another domain via NLP are routed to the system
domain automatically.  This is controlled by `role_defaults` in
`cfg/domain-registry.yaml` and implemented in
`DomainRegistry.resolve_default_for_user()` in `src/lumina/core/domain_registry.py`.

All other roles (including unauthenticated users) fall through to the global
`default_domain: education`.  This intentional asymmetry hides system internals
from domain-level users by default.

### What system domain sessions support

- **Glossary queries** — explain any term in the system-core domain physics glossary
  (System Log, commitment record, RBAC, domain pack, policy gate, hash chain, etc.)
- **Status queries** — discuss the state of a Lumina component from session context
- **Diagnostic discussion** — troubleshooting guidance for runtime issues
- **Config review** — walk through domain-registry, domain-physics, or system-physics
- **Operational monitoring** — System Log record structure, night-cycle status, hash-chain
  integrity

The system domain does **not** support world-sim personas, learner ZPD tracking,
or any domain-level tool adapters beyond core Lumina.

---

## B — System Log

The system domain has its own System Logs located at
`$LUMINA_LOG_DIR/system/system.jsonl` (default:
`$env:TEMP/lumina-log/system/system.jsonl` on Windows).

### Commitment record types in the system log

| Type | When written | Script |
|------|-------------|--------|
| `system_physics_activation` | On first compile of a new `system-physics.json` hash | `scripts/seed-system-physics-log.ps1` |
| `system_physics_rollback` | When rolling back to a previous hash | manual — see rollback procedure below |

### Hash chaining

Every CommitmentRecord in the system log carries:

- `subject_hash` — SHA-256 of the compiled `system-physics.json`
- `previous_hash` — SHA-256 of the previous ledger record (or all-zeros for genesis)
- `record_hash` — SHA-256 of the current record itself (tamper-evidence)

TraceEvents in named-domain sessions carry a `system_physics_hash` metadata field
in their `Evidence` object that must match the most recent activated entry in the
system log.

---

## C — System physics activation workflow

Follow this workflow whenever `cfg/system-physics.yaml` is edited.

### 1 — Edit source YAML

```
cfg/system-physics.yaml
```

- Bump the `version` field (semver; editorial changes → patch; new
  invariants → minor; breaking schema changes → major).
- Add or update entries in the `glossary:` block as needed.

### 2 — Compile and validate

```powershell
.\.venv\Scripts\lumina-yaml-convert.exe cfg/system-physics.yaml `
    --output cfg/system-physics.json `
    --schema standards/system-physics-schema-v1.json
```

Expected output:

```
Validation: PASSED ✓
Content hash (SHA-256): <64-char hex>
Written: cfg\system-physics.json
```

A validation failure means either the YAML data does not conform to
`standards/system-physics-schema-v1.json` or a required field is missing.
Fix the YAML and rerun; do **not** hand-edit the compiled JSON.

### 3 — Commit hash to system log

```powershell
.\scripts\seed-system-physics-log.ps1 `
    -PythonExe ".\.venv\Scripts\python.exe" `
    -ActorId "<your-actor-id>"
```

Expected output:

```
subject_version: <version>
subject_hash:    <sha256>
Status: committed [OK]
record_id: <uuid>
```

If the hash is already committed, the script is idempotent and reports
`Status: already committed`.

### 4 — Regenerate manifest

```powershell
.\.venv\Scripts\lumina-manifest-regen.exe
```

This recomputes SHA-256 values for all tracked artifacts including the updated
`cfg/system-physics.json` and `standards/system-physics-schema-v1.json`.

### Rollback procedure

To revert to a previous physics version:

1. Restore the previous `cfg/system-physics.yaml` from version control.
2. Rerun steps 2–4 above.
3. Append a `system_physics_rollback` CommitmentRecord to the system log
   manually (schema: `ledger/commitment-record-schema.json`).
4. Document the rollback reason in the governance audit log.

See `governance/audit-and-rollback.md` for the full rollback policy.

---

## D — Auditor read scope

Roles with `auditor` or above may read the system log and all physics files.
No role below `root` may edit system physics without a CommitmentRecord being
appended first (policy gate enforced at startup).

| Operation | Minimum role |
|-----------|-------------|
| Read `cfg/system-physics.json` | `auditor` |
| Read system System Log ledger | `auditor` |
| Activate new system physics | `root` |
| Roll back system physics | `root` |
| Edit `standards/system-physics-schema-v1.json` | `root` |

Auditors may use `lumina-system-log-validate` to verify the hash chain:

```powershell
.\.venv\Scripts\lumina-system-log-validate.exe `
    --ledger "$env:TEMP\lumina-log\system\system.jsonl"
```

---

## E — Glossary intercept in the system domain context

The `glossary:` block in `cfg/system-physics.yaml` provides the controlled
vocabulary for Lumina infrastructure terms.  It is compiled into
`cfg/system-physics.json` and surfaced by the glossary-intercept pipeline
when the NLP semantic router classifies a message as belonging to the system
domain.

### Routing surface

`classify_domain()` uses the `keywords:` list from the `system:` entry in
`cfg/domain-registry.yaml` to route admin and auditor queries.  Example
terms that trigger system-domain routing: `ctl`, `ledger`, `invariant`,
`standing order`, `tool adapter`, `domain physics`, `rbac`, `orchestrator`.

### Glossary intercept pipeline

```
Incoming message
      │
      ▼
classify_domain()   ← domain-registry.yaml keywords
      │  (system domain)
      ▼
glossary_intercept()  ← scans against system glossary terms + aliases
      │  (term match found)
      ▼
Return definition + related_terms
      │  (no match)
      ▼
Route to NLP pre-interpreter as normal
```

When a match is found, the intercept returns the `definition`,
`related_terms`, and (if present) `example_in_context` fields directly
without invoking the LLM on an infrastructure definition question.

### Current glossary terms

The following 19 terms are defined in `cfg/system-physics.yaml` v1.1.0:

`commitment_record` · `trace_event` · `escalation_record` ·
`system_logs` · `system_physics` · `domain_physics` ·
`prompt_contract` · `standing_order` · `invariant` · `escalation_trigger` ·
`policy_commitment_gate` · `domain_pack` · `domain_authority` ·
`meta_authority` · `domain_registry` · `pseudonymous_id` · `rbac` ·
`tool_adapter` · `orchestrator` · `domain_lib`
