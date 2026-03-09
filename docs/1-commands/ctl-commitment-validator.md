# ctl-commitment-validator(1)

## NAME

`ctl-commitment-validator.py` — Commit and verify domain pack hashes in the Causal Trace Ledger

## SYNOPSIS

```bash
# Verify a ledger
python reference-implementations/ctl-commitment-validator.py \
  --verify <ledger-file>

# Commit a domain pack hash
python reference-implementations/ctl-commitment-validator.py \
  --commit <domain-physics-json> \
  --actor-id <pseudonymous-id> \
  --ledger <ledger-file>

# Print ledger contents
python reference-implementations/ctl-commitment-validator.py \
  --print-ledger <ledger-file>
```

## DESCRIPTION

Manages CommitmentRecords in the CTL. Before a domain pack is activated, its domain-physics.json hash must be committed. At session time the runtime verifies the active hash matches a committed record.

## SEE ALSO

[verify-repo-integrity(1)](verify-repo-integrity.md), [audit-and-rollback](../../governance/audit-and-rollback.md)
