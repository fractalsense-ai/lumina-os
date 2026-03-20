---
version: 1.0.0
last_updated: 2026-03-20
---

# yaml-to-json-converter(1)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`yaml-to-json-converter.py` — Convert domain-physics YAML to validated JSON

## SYNOPSIS

```bash
python reference-implementations/yaml-to-json-converter.py <yaml-file> \
  [--schema <schema-file>] [--output <output-file>]
```

## DESCRIPTION

Converts a domain-physics YAML source file to its machine-authoritative JSON representation. Optionally validates the output against the domain-physics JSON schema.

## OPTIONS

- `<yaml-file>` — Path to the domain-physics YAML source (required)
- `--schema <schema-file>` — JSON schema to validate against (optional)
- `--output <output-file>` — Custom output path; defaults to same directory as input with `.json` extension

## EXAMPLES

```bash
# Convert only
python reference-implementations/yaml-to-json-converter.py \
  domain-packs/education/modules/algebra-level-1/domain-physics.yaml

# Convert and validate
python reference-implementations/yaml-to-json-converter.py \
  domain-packs/education/modules/algebra-level-1/domain-physics.yaml \
  --schema standards/domain-physics-schema-v1.json
```

## SEE ALSO

[system-log-validator(1)](system-log-validator.md), [domain-physics-schema](../../standards/domain-physics-schema-v1.json)
