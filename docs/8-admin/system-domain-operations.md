# system-domain-operations

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-13  

---

Operational reference for the Project Lumina system domain: the machine-readable
policy layer (`cfg/system-physics.yaml`) that governs the Conversational Interface
before and regardless of which named domain is active.

---

## A — System domain overview

The **system domain** is not a named domain pack (it has no `domain-packs/system/`
directory).  Instead it comprises:

| Component | Path | Role |
|-----------|------|------|
| System physics source | `cfg/system-physics.yaml` | Human-editable policy source |
| System physics compiled | `cfg/system-physics.json` | Runtime-loaded, schema-validated |
| System physics schema | `standards/system-physics-schema-v1.json` | JSON Schema for CI layer |
| Domain registry entry | `cfg/domain-registry.yaml` → `system:` | Enables glossary routing |
| Runtime config stub | `cfg/system-runtime-config.yaml` | Routing-only; live sessions unimplemented |
| System lib | `src/lumina/lib/system_health.py` | Passive state estimator (hw probes) |
| Hardware probes | `src/lumina/systools/hw_disk.py` · `hw_temp.py` · `hw_memory.py` | Passive, lib-invoked only |

The system domain registry entry is present so that `classify_domain()` can route
admin and auditor queries about Lumina infrastructure terms to the system glossary
via the glossary-intercept pipeline.  **Live session execution is not yet
implemented** (the stub runtime config restricts access to `root`).

---

## B — System CTL

The system domain has its own Causal Trace Ledger located at
`$LUMINA_CTL_DIR/system/system.jsonl` (default:
`$env:TEMP/lumina-ctl/system/system.jsonl` on Windows).

### Commitment record types in the system CTL

| Type | When written | Script |
|------|-------------|--------|
| `system_physics_activation` | On first compile of a new `system-physics.json` hash | `scripts/seed-system-physics-ctl.ps1` |
| `system_physics_rollback` | When rolling back to a previous hash | manual — see rollback procedure below |

### Hash chaining

Every CommitmentRecord in the system CTL carries:

- `subject_hash` — SHA-256 of the compiled `system-physics.json`
- `previous_hash` — SHA-256 of the previous ledger record (or all-zeros for genesis)
- `record_hash` — SHA-256 of the current record itself (tamper-evidence)

TraceEvents in named-domain sessions carry a `system_physics_hash` metadata field
in their `Evidence` object that must match the most recent activated entry in the
system CTL.

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

### 3 — Commit hash to system CTL

```powershell
.\scripts\seed-system-physics-ctl.ps1 `
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
3. Append a `system_physics_rollback` CommitmentRecord to the system CTL
   manually (schema: `ledger/commitment-record-schema.json`).
4. Document the rollback reason in the governance audit log.

See `governance/audit-and-rollback.md` for the full rollback policy.

---

## D — Auditor read scope

Roles with `auditor` or above may read the system CTL and all physics files.
No role below `root` may edit system physics without a CommitmentRecord being
appended first (policy gate enforced at startup).

| Operation | Minimum role |
|-----------|-------------|
| Read `cfg/system-physics.json` | `auditor` |
| Read system CTL ledger | `auditor` |
| Activate new system physics | `root` |
| Roll back system physics | `root` |
| Edit `standards/system-physics-schema-v1.json` | `root` |

Auditors may use `lumina-ctl-validate` to verify the hash chain:

```powershell
.\.venv\Scripts\lumina-ctl-validate.exe `
    --ledger "$env:TEMP\lumina-ctl\system\system.jsonl"
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
`causal_trace_ledger` · `system_physics` · `domain_physics` ·
`prompt_contract` · `standing_order` · `invariant` · `escalation_trigger` ·
`policy_commitment_gate` · `domain_pack` · `domain_authority` ·
`meta_authority` · `domain_registry` · `pseudonymous_id` · `rbac` ·
`tool_adapter` · `orchestrator` · `domain_lib`
