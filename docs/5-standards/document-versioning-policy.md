---
version: 1.1.0
last_updated: 2026-04-16
---

# document-versioning-policy(5)

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-04-16  

---

## NAME

`document-versioning-policy` — Version control standards for all Project Lumina artifacts

## SYNOPSIS

Every artifact managed by Project Lumina must carry a version header, a status field, and a
last-updated date. All artifacts are indexed in `docs/MANIFEST.yaml` with SHA-256 integrity
records.

## DESCRIPTION

This standard establishes the rules for versioning, status lifecycle, and hash-based integrity
across all artifact types in the Project Lumina repository: documentation (`docs/`),
specifications (`specs/`), standards (`standards/`), JSON schemas, tool adapter declarations,
and domain libraries.

The goal is navigability — an AI or human reader arriving at any artifact can know exactly what
version they are reading, whether it supersedes anything, and verify its integrity against the
manifest.

---

## HEADER FORMAT

Every markdown artifact must include the following three-line block immediately after its
top-level heading, separated by a blank line before and after, followed by a horizontal rule:

```
**Version:** X.Y.Z  
**Status:** Active  
**Last updated:** YYYY-MM-DD  

---
```

For JSON schema artifacts, the equivalent metadata is carried in `docs/MANIFEST.yaml` only and
referenced by the schema's `$id` field. No embedded header is added to JSON files.

---

## VERSIONING RULES

Versions follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

### PATCH bump

Clarifications, typo corrections, rewording with no behavioral or structural change. The
artifact's meaning is identical to the previous version.

- Example: correcting a code sample, fixing a dead link, rephrasing a description.

### MINOR bump

Additive changes that are backward-compatible: new sections, new fields, new OPTIONS entries,
expanded EXAMPLES. Existing behavior or structure is fully preserved.

- Example: adding a new `--flag` to a command SYNOPSIS; adding a row to a reference table.

### MAJOR bump

Breaking changes, structural reorganization, removal of sections or fields, or a change in
normative behavior. Existing content that depends on the previous version must be re-read.

- Example: renaming a mandatory JSON field, removing an API endpoint, restructuring a schema.

When MAJOR is bumped, MINOR and PATCH reset to 0. When MINOR is bumped, PATCH resets to 0.

---

## STATUS VALUES

| Status | Meaning |
|--------|---------|
| `Draft` | Artifact is not yet authoritative; may change without notice. |
| `Active` | Artifact is the current authoritative version. |
| `Deprecated` | Artifact is superseded and will be removed at the next major version boundary. Still operable. |
| `Superseded` | Artifact has been replaced. The `superseded_by` field in `MANIFEST.yaml` points to the replacement. |

A `Deprecated` or `Superseded` artifact must not be deleted. Its status header and manifest entry
must be updated and retained until the next major version boundary.

---

## CHANGE TRIGGER TABLE

The following table maps artifact type to the events that trigger each version bump level.

| Artifact Type | PATCH | MINOR | MAJOR |
|---|---|---|---|
| `doc` (docs/) | Wording, links | New sections, new examples | Section removal, structural rewrite |
| `spec` (specs/) | Clarification | New normative fields, extended behavior | Breaking behavioral change, removal |
| `standard` (standards/*.md) | Wording | New conformance requirement (additive) | Breaking conformance requirement |
| `schema` (*.json) | `description` wording | New optional field | New required field, field removal, type change |
| `tool-adapter` (YAML) | Metadata-only edits | New optional input/output field | Required field added/removed, type changed, `domain_id` changed |
| `domain-library` | Docstrings, comments | New method or output field (additive) | Method signature change, method removal, output field removed |

---

## HASH INTEGRITY

Each artifact's SHA-256 hash is recorded in `docs/MANIFEST.yaml`. The hash covers the raw file
bytes at the time of the last write.

Hash records follow the same philosophy as `CommitmentRecord` entries in the System Logs: the hash lives
externally in an authoritative ledger, not embedded in the file itself — embedding would create
a self-referential bootstrap problem.

**Verification procedure:**

1. Locate the artifact entry in `docs/MANIFEST.yaml` by `path`.
2. Compute `sha256(raw_file_bytes)` of the artifact on disk.
3. Compare against the `sha256` field in the manifest entry.
4. A mismatch indicates the artifact was modified without a corresponding manifest update.

---

## UPDATING THE MANIFEST

After any artifact is modified:

1. Bump the artifact's version header (PATCH/MINOR/MAJOR per rules above).
2. Update `last_updated` in the artifact's header to today's date.
3. Recompute the SHA-256 hash of the artifact's raw bytes.
4. Update the corresponding entry in `docs/MANIFEST.yaml`: `doc_version`, `last_updated`, `sha256`.
5. Update `last_updated` at the top of `docs/MANIFEST.yaml`.

---

## FUTURE WORK

A `verify-manifest-integrity` script — analogous to `verify-repo-integrity.py` — is planned to
automate SHA-256 verification and flag stale manifest entries on commit. Until that script
exists, manifest hashes must be updated manually whenever an artifact is modified.

---

## IMPLEMENTATION VS. SPECIFICATION VERSIONING

Project Lumina maintains two independent version tracks:

| Track | Location | Current | What it tracks |
|-------|----------|---------|----------------|
| **Implementation** | `pyproject.toml` | 0.1.0 | The software — API server, orchestrator, persistence, tests |
| **Specification** | `standards/lumina-core-v1.md` | 1.1.0 | The formal spec — D.S.A. contracts, PPA protocol, System Log schema |

These tracks **intentionally diverge**. The specification leads: it defines the target behavior.
The implementation follows: it catches up to the spec incrementally. A spec version bump does
not require an implementation version bump, and vice versa.

The root [`CHANGELOG.md`](../../CHANGELOG.md) tracks the implementation version. Specification
changes are tracked in the spec document's own version header and in `docs/MANIFEST.yaml`.

---

## SEE ALSO

[artifact-manifest-format(4)](../4-formats/artifact-manifest-format.md),
[tool-adapter-versioning(4)](../4-formats/tool-adapter-versioning.md),
[domain-library-lifecycle(5)](domain-library-lifecycle.md),
[verify-repo-integrity(1)](../1-commands/verify-repo-integrity.md)
