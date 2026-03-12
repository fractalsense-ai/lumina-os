# artifact-manifest-format(4)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`artifact-manifest-format` — Format specification for `docs/MANIFEST.yaml`

## SYNOPSIS

`docs/MANIFEST.yaml` — machine-readable, AI-navigable registry of all versioned Project Lumina
core artifacts

## DESCRIPTION

`docs/MANIFEST.yaml` is the central artifact registry for the Project Lumina core repository.
It maps every versioned artifact (docs, specs, standards, schemas) to its current version,
status, last-updated date, and SHA-256 integrity hash.

Domain packs maintain their own per-pack `MANIFEST.yaml` at the root of each domain pack
directory (e.g., `domain-packs/education/MANIFEST.yaml`). The core manifest does not index
domain-pack artifacts.

### AI Navigation Pattern

An AI agent navigating the repository should:

1. Read `docs/MANIFEST.yaml` to discover all available artifacts and their current versions.
2. Locate the target artifact by `path` and read it.
3. Optionally verify `sha256` against the local file to confirm the artifact has not drifted
   from the indexed version.
4. Use `status` to skip `Deprecated` or `Superseded` entries; follow `superseded_by` to the
   current replacement.

---

## TOP-LEVEL FIELDS

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string (semver) | Yes | Version of the MANIFEST format schema itself. Currently `1.0.0`. |
| `last_updated` | string (YYYY-MM-DD) | Yes | Date the manifest was last regenerated or modified. |
| `artifacts` | list | Yes | Ordered list of artifact entries. See ARTIFACT ENTRY below. |

---

## ARTIFACT ENTRY FIELDS

| Field | Type | Required | Description |
|---|---|---|---|
| `path` | string | Yes | Workspace-relative path from repository root (e.g., `docs/1-commands/ctl-commitment-validator.md`). |
| `type` | string | Yes | Artifact type: `doc`, `spec`, `standard`, `schema`, `tool-adapter`, `domain-library`. |
| `section` | integer | Docs only | Unix man-page section number (1–8). Omit for non-doc artifacts. |
| `doc_version` | string (semver) | Yes | Current semver version of the artifact's content. |
| `status` | string | Yes | `draft`, `active`, `deprecated`, or `superseded`. |
| `last_updated` | string (YYYY-MM-DD) | Yes | Date the artifact content was last changed. |
| `sha256` | string | Yes | Lowercase hex SHA-256 digest of the artifact's raw bytes. The reserved value `pending` is valid only during initial bootstrap. |
| `superseded_by` | string | Conditional | Workspace-relative path to the replacement artifact. Required when `status` is `superseded`. |

---

## EXAMPLE MANIFEST SNIPPET

```yaml
schema_version: 1.0.0
last_updated: 2026-03-12

artifacts:
  - path: docs/1-commands/ctl-commitment-validator.md
    type: doc
    section: 1
    doc_version: 1.0.0
    status: active
    last_updated: 2026-03-12
    sha256: pending

  - path: standards/tool-adapter-schema-v1.json
    type: schema
    doc_version: 1.0.0
    status: active
    last_updated: 2026-03-08
    sha256: pending

  - path: specs/dsa-framework-v1.md
    type: spec
    doc_version: 1.2.0
    status: active
    last_updated: 2026-03-08
    sha256: pending

  - path: specs/principles-v1.md
    type: spec
    doc_version: 1.0.0
    status: superseded
    last_updated: 2026-02-01
    sha256: pending
    superseded_by: specs/principles-v2.md
```

---

## RECOMMENDED ARTIFACT ORDERING

Entries should be ordered by type, then by section (for docs), then alphabetically. Suggested
order: `doc` (sections 1–8), `spec`, `standard`, `schema`.

---

## VERSIONING THE MANIFEST ITSELF

The manifest format is versioned via `schema_version`. Rules:

- Bump PATCH when artifact entries are added or updated (routine operation).
- Bump MINOR when new artifact entry fields are introduced (backward-compatible addition).
- Bump MAJOR when existing fields are renamed, removed, or semantically changed.

---

## SEE ALSO

[document-versioning-policy(5)](../5-standards/document-versioning-policy.md),
[tool-adapter-versioning(4)](tool-adapter-versioning.md),
[domain-library-lifecycle(5)](../5-standards/domain-library-lifecycle.md),
[MANIFEST.yaml](../MANIFEST.yaml)
