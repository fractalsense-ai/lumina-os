---
version: 1.0.0
last_updated: 2026-03-20
---

# domain-library-lifecycle(5)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`domain-library-lifecycle` — Version lifecycle for domain packs and domain libraries

## SYNOPSIS

Domain packs and the domain libs they contain are versioned artifacts with explicit lifecycle
rules. This document defines what triggers version bumps, what must be recorded in
`CHANGELOG.md`, and how domain library versions relate to System Log commitment records.

## DESCRIPTION

A domain pack contains two versioned sub-artifacts with related but independent lifecycles:

1. **Domain physics document** (`domain-physics.yaml` / `domain-physics.json`) — The immutable
   ruleset defining what is true in the domain. Its version is embedded in the document's
   `version` field and its SHA-256 hash is committed to the System Logs before activation.

2. **Domain library (domain lib)** — Deterministic estimators and signal processors that compute
   the compressed state fed to the D.S.A. engine. Conformant with the
   [Domain State Lib Contract](../../standards/domain-state-lib-contract-v1.md).

Both must have `CHANGELOG.md` entries for every version change. The `CHANGELOG.md` at the domain
pack root is required by [lumina-core-v1](../../standards/lumina-core-v1.md).

---

## DOMAIN PACK VERSION BUMP RULES

The domain pack version is carried in `domain-physics.yaml` (and its derived
`domain-physics.json`).

| Change | Bump Level | Notes |
|---|---|---|
| Clarification in descriptions, wording fixes | PATCH | Does not change JSON output; hash unchanged. |
| New optional field added to domain-physics | MINOR | Additive; existing sessions remain valid. |
| New tool adapter added (optional reference) | MINOR | Domain-physics hash changes; new commitment required. |
| New required field in domain-physics | MAJOR | Breaking — existing activations invalid; new commitment required. |
| Existing field removed or type changed | MAJOR | Breaking; new commitment required. |
| Module permissions `mode` changed (RBAC) | MAJOR | Security-relevant; new commitment required. |
| `domain_id` changed | MAJOR | Treat as a new domain pack entirely. |

Any change that modifies the content of `domain-physics.json` (the machine-authoritative file)
changes its SHA-256 hash and **requires a new `CommitmentRecord`** in the System Logs before the pack
can be activated.

---

## DOMAIN LIBRARY VERSION BUMP RULES

The domain lib version is tracked in the pack's `MANIFEST.yaml` (under the relevant lib module
paths) and in `CHANGELOG.md`.

| Change | Bump Level | Notes |
|---|---|---|
| Docstring or comment updates | PATCH | No behavioral change. |
| Threshold constant tuned (same logic, new value) | PATCH | Behavioral micro-change within specification tolerance. |
| New estimator method added (additive) | MINOR | Additive; existing callers unaffected. |
| New field added to output dict | MINOR | Engine contract extended, backward-compatible. |
| Existing method renamed or signature changed | MAJOR | Breaking for all callers. |
| Method removed | MAJOR | Breaking. |
| Output field removed or type changed | MAJOR | Breaking for engine contract consumers. |
| Domain lib split into sub-modules | MAJOR | Import paths change. |

Domain library changes that do not touch `domain-physics.json` do not require a new System Log
commitment, but the library version and `CHANGELOG.md` must still be updated.

---

## CHANGELOG REQUIREMENTS

Every domain pack `CHANGELOG.md` must follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format with semver headers:

```markdown
## [1.1.0] — 2026-03-12

### Added
- New `cognitive_load_index` signal in ZPD estimator output (domain-lib MINOR bump).

## [1.0.0] — 2026-03-01

### Added
- Initial release of algebra-level-1 domain pack.
```

Entries must describe: what changed, which artifact was affected (domain-physics, lib module,
or tool adapter), and — for MAJOR changes — what downstream artifacts must be updated as a
result.

---

## SYSTEM LOG COMMITMENT TRIGGER

When `domain-physics.json` is modified (any MINOR or MAJOR bump to the domain pack), commit the
new hash before activating the pack:

```bash
python reference-implementations/system-log-validator.py \
  --commit domain-packs/{domain}/modules/{module}/domain-physics.json \
  --actor-id <pseudonymous-id> \
  --ledger <ledger-file>
```

The System Logs `CommitmentRecord` becomes the auditable proof that the domain pack at a specific version
was reviewed and approved for activation. Any session using the pack after this point has a
traceable lineage to that record.

---

## SEE ALSO

[domain-state-lib-contract-v1](../../standards/domain-state-lib-contract-v1.md),
[lumina-core-v1](../../standards/lumina-core-v1.md),
[document-versioning-policy(5)](document-versioning-policy.md),
[system-log-validator(1)](../1-commands/system-log-validator.md),
[artifact-manifest-format(4)](../4-formats/artifact-manifest-format.md),
[domain-adapter-pattern(7)](../7-concepts/domain-adapter-pattern.md)
