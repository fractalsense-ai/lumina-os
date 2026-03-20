---
version: 1.0.0
last_updated: 2026-03-20
---

# system-log-validator(1)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`system-log-validator.py` — Commit and verify domain pack hashes in the System Logs

## SYNOPSIS

```bash
# Verify a ledger
python reference-implementations/system-log-validator.py \
  --verify <ledger-file>

# Commit a domain pack hash
python reference-implementations/system-log-validator.py \
  --commit <domain-physics-json> \
  --actor-id <pseudonymous-id> \
  --ledger <ledger-file>

# Print ledger contents
python reference-implementations/system-log-validator.py \
  --print-ledger <ledger-file>
```

## DESCRIPTION

Manages CommitmentRecords in the System Logs. Before a domain pack is activated, its domain-physics.json hash must be committed. At session time the runtime verifies the active hash matches a committed record.

## SEE ALSO

[verify-repo-integrity(1)](verify-repo-integrity.md), [audit-and-rollback](../../governance/audit-and-rollback.md)
