# integrity-check(1)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`lumina-integrity-check` — Verify SHA-256 hashes for all core artifacts in `docs/MANIFEST.yaml`

## SYNOPSIS

```bash
# Installed entry point
lumina-integrity-check

# PowerShell (Windows)
scripts\integrity-check.ps1 [-PythonExe <path>]

# Bash (Unix / WSL)
bash scripts/integrity-check.sh

# Direct module invocation
python -m lumina.systools.manifest_integrity check
```

## DESCRIPTION

Reads `docs/MANIFEST.yaml` and verifies that the SHA-256 hash recorded for each artifact
matches the hash of the file currently on disk.

Each artifact is assigned one of four statuses:

| Status    | Meaning                                                                          |
|-----------|----------------------------------------------------------------------------------|
| `OK`      | Recorded hash matches the file on disk. Suppressed in normal output.             |
| `MISMATCH`| Recorded hash does not match the file. **Triggers exit code 1.**                 |
| `PENDING` | Hash recorded as `pending` (not yet computed). Warning only — does not fail.     |
| `MISSING` | File not found on disk. Warning only — does not fail.                            |

`MISMATCH` entries indicate an artifact was modified without a corresponding manifest
update. Review the change and run `manifest-regenerate(1)` to bring the manifest back
into sync.

`PENDING` entries are expected during initial bootstrapping or when a new artifact entry
has been added but not yet hashed. Resolve them by running `manifest-regenerate(1)`.

Domain-pack artifact integrity is managed by the Causal Trace Ledger (CTL), not by
this tool. See `ctl-commitment-validator(1)`.

## EXIT CODES

- `0` — All hashes match (PENDING and MISSING entries produce warnings, exit is still 0)
- `1` — One or more MISMATCH entries detected

## ENVIRONMENT

`PYTHON` — Override the Python interpreter used by the Bash script. Defaults to `python3`.

## SEE ALSO

[manifest-regenerate(1)](manifest-regenerate.md), [verify-repo-integrity(1)](verify-repo-integrity.md), [artifact-manifest-format(4)](../4-formats/artifact-manifest-format.md), [ctl-commitment-validator(1)](ctl-commitment-validator.md)
