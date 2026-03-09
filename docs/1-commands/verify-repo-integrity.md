# verify-repo-integrity(1)

## NAME

`verify-repo-integrity.py` — Run repository-wide integrity checks

## SYNOPSIS

```bash
python reference-implementations/verify-repo-integrity.py
```

## DESCRIPTION

Validates cross-file consistency across the repository: version alignment between YAML/JSON/CHANGELOG, link integrity in documentation, schema conformance, provenance key naming, and domain-physics hash drift.

## EXIT CODES

- `0` — All checks passed
- `1` — One or more integrity errors found (printed to stderr)

## SEE ALSO

[ctl-commitment-validator(1)](ctl-commitment-validator.md), [audit-and-rollback](../../governance/audit-and-rollback.md)
