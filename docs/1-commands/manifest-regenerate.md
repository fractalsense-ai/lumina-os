---
version: 1.0.0
last_updated: 2026-03-20
---

# manifest-regenerate(1)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`lumina-manifest-regen` — Recompute and rewrite SHA-256 hashes in `docs/MANIFEST.yaml`

## SYNOPSIS

```bash
# Installed entry point
lumina-manifest-regen

# PowerShell (Windows)
scripts\manifest-regenerate.ps1 [-PythonExe <path>]

# Bash (Unix / WSL)
bash scripts/manifest-regenerate.sh

# Direct module invocation
python -m lumina.systools.manifest_integrity regen
```

## DESCRIPTION

Computes the SHA-256 hash of every artifact listed in `docs/MANIFEST.yaml` that exists
on disk and rewrites the `sha256:` values in-place. The top-level `last_updated:` date
is also updated to today's date in `YYYY-MM-DD` format.

Formatting, comments, and all non-hash fields in `docs/MANIFEST.yaml` are fully preserved.
Only `sha256:` values and the top-level `last_updated:` field are modified.

Artifacts that are not found on disk receive a printed warning; their `sha256:` entries
are left unchanged. No artifact entries are added or removed — this tool only updates
existing hash values.

**When to run:**

- After modifying any artifact listed in `docs/MANIFEST.yaml`
- After adding a new artifact entry with `sha256: pending`
- When `integrity-check(1)` reports a `MISMATCH`
- As part of the release preparation workflow before tagging a version

Domain-pack artifact hashes are committed via `system-log-validator(1)`, not this
tool. Do not use this script to manage System Log ledger integrity.

## EXIT CODES

- `0` — Hash values written successfully
- `1` — An error prevented writing (e.g., MANIFEST.yaml parse failure)

## PERMISSIONS

**Required permission:** Write (w)

| Context | Details |
|---------|---------|
| Allowed roles | `root`, `admin` |
| Denied roles | `super_admin`, `operator`, `half_operator`, `user` |
| API endpoint | `POST /api/manifest/regen` |
| Auth required | Yes (JWT) |

This is a write operation that modifies `docs/MANIFEST.yaml` in-place. It is restricted to roles
that carry authoring authority over repository artifacts. Auditors and operator personnel may inspect
the manifest via `integrity-check(1)` (`GET /api/manifest/check`) but may not rewrite it.

All API invocations are recorded as a System Log `TraceEvent` on the `_admin` ledger for auditability.

## ENVIRONMENT

`PYTHON` — Override the Python interpreter used by the Bash script. Defaults to `python3`.

## SEE ALSO

[integrity-check(1)](integrity-check.md), [system-log-validator(1)](system-log-validator.md), [document-versioning-policy(5)](../5-standards/document-versioning-policy.md), [artifact-manifest-format(4)](../4-formats/artifact-manifest-format.md)
