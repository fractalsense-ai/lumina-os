# yaml-to-json-converter(1)

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

[ctl-commitment-validator(1)](ctl-commitment-validator.md), [domain-physics-schema](../../standards/domain-physics-schema-v1.json)
