# tool-adapter-versioning(4)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`tool-adapter-versioning` — Version lifecycle for tool adapter YAML declarations

## SYNOPSIS

Tool adapter declarations (`tool-adapters/*.yaml` in each domain pack) carry a `version` field
defined by [`tool-adapter-schema-v1.json`](../../standards/tool-adapter-schema-v1.json). This
document defines when that version must be bumped and how adapters are tracked in domain-pack
manifests.

## DESCRIPTION

A tool adapter declaration defines the contract between the D.S.A. orchestrator and an external
tool: acceptable inputs, expected outputs, authorization requirements, and the domain that owns
the tool. The `version` field in the adapter YAML is a semantic version string and is the
primary versioning identifier for that adapter.

Tool adapter YAMLs are **not** indexed in `docs/MANIFEST.yaml`. Each domain pack maintains its
own `MANIFEST.yaml` at the pack root (e.g., `domain-packs/education/MANIFEST.yaml`) that indexes
the pack's adapters and domain-library modules.

---

## VERSION BUMP RULES

The following events require a version bump on a tool adapter:

| Change | Bump Level | Rationale |
|---|---|---|
| Metadata edits (`description`, `tool_name` text only) | PATCH | No behavioral contract change. |
| New optional field in `input_schema` or `output_schema` | MINOR | Additive; existing callers unaffected. |
| Stricter constraint on existing input field (e.g., narrowed `enum`, tighter `maxLength`) | MINOR | Callers must be aware of the added restriction. |
| New `authorization` scope added (additive) | MINOR | Existing sessions remain valid. |
| Required input or output field added | MAJOR | Breaking change for all callers. |
| Required input or output field removed | MAJOR | Breaking change. |
| Input or output field type changed | MAJOR | Breaking change. |
| `domain_id` changed | MAJOR | Ownership transferred; treat as a new adapter. |
| Authorization scope removed | MAJOR | May invalidate sessions depending on the removed scope. |

---

## ADAPTER `id` AND VERSION ALIGNMENT

The `id` field in a tool adapter follows the format:

```
adapter/{domain-short}/{tool-name}/v{major}
```

When a MAJOR version bump occurs, the `id` must update its `v{major}` suffix (e.g.,
`adapter/edu/hint-generator/v1` → `adapter/edu/hint-generator/v2`). The prior adapter YAML
should be retained and its status updated to `superseded` in the pack's `MANIFEST.yaml`, with a
`superseded_by` pointer to the new adapter path.

---

## RELATIONSHIP TO CTL COMMITMENT RECORDS

A `CommitmentRecord` in the CTL records the SHA-256 of `domain-physics.json` at the time of
domain activation. Tool adapter versions are not independently committed to the CTL; however,
any change to an adapter that is embedded in or referenced by `domain-physics.json` changes that
file's content and therefore its hash.

This creates an indirect but auditable version trace: the CTL chain records when a new
domain-physics hash (which reflects the adapter change) was committed and by whom. See
[domain-library-lifecycle(5)](../5-standards/domain-library-lifecycle.md) for the full
commitment trigger table.

---

## SEE ALSO

[tool-adapter-schema-v1.json](../../standards/tool-adapter-schema-v1.json),
[artifact-manifest-format(4)](artifact-manifest-format.md),
[document-versioning-policy(5)](../5-standards/document-versioning-policy.md),
[domain-library-lifecycle(5)](../5-standards/domain-library-lifecycle.md),
[ctl-commitment-validator(1)](../1-commands/ctl-commitment-validator.md),
[domain-adapter-pattern(7)](../7-concepts/domain-adapter-pattern.md)
