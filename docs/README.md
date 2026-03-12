# Project Lumina — Documentation Index

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

Documentation is organized using the UNIX man-page section convention.

| Section | Name | Contents |
|---------|------|----------|
| [1](1-commands/) | Commands | CLI tools and utilities |
| [2](2-syscalls/) | System Calls | API endpoints and server interface |
| [3](3-functions/) | Functions | Library interfaces (auth, permissions, persistence) |
| [4](4-formats/) | Formats | File formats, schemas, and data structures |
| [5](5-standards/) | Standards | Core standards and protocol specifications |
| [6](6-examples/) | Examples | Worked examples, traces, and tutorials |
| [7](7-concepts/) | Concepts | Architecture, principles, and design frameworks |
| [8](8-admin/) | Administration | Governance, audit, RBAC, and operational policy |

---

## Quick Start

1. **Concepts** — Read [principles](../specs/principles-v1.md) and the [D.S.A. framework](../specs/dsa-framework-v1.md)
2. **Standards** — Review [lumina-core](../standards/lumina-core-v1.md) and [RBAC](../specs/rbac-spec-v1.md)
3. **Formats** — Understand [domain-physics schema](../standards/domain-physics-schema-v1.json) and [prompt-contract schema](../standards/prompt-contract-schema-v1.json)
4. **Commands** — Start with [installation and packaging](1-commands/installation-and-packaging.md), then use the [YAML converter](1-commands/yaml-to-json-converter.md) and [CTL validator](1-commands/ctl-commitment-validator.md)
5. **API** — Browse the [API server reference](2-syscalls/lumina-api-server.md)
6. **Examples** — Study the [causal learning trace](../examples/causal-learning-trace-example.json)
7. **Admin** — Configure [runtime secrets](8-admin/secrets-and-runtime-config.md), [RBAC roles](8-admin/rbac-administration.md), and [audit policy](../governance/audit-and-rollback.md)

---

Domain-specific documentation (education prompts, agriculture adapters, etc.) stays in [`../domain-packs/`](../domain-packs/).

---

## Versioning

All artifacts in this repository are versioned with semver headers, status fields, and
SHA-256 integrity records. See [document-versioning-policy(5)](5-standards/document-versioning-policy.md)
for the full rules.

The machine-readable artifact index is at [MANIFEST.yaml](MANIFEST.yaml). AI agents and
automated tooling should read the manifest first to discover current artifact versions,
verify integrity, and follow `superseded_by` pointers before reading any artifact.
