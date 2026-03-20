---
version: 1.0.0
last_updated: 2026-03-20
---

# RBAC Administration

**Version:** 1.2.0
**Status:** Active
**Last updated:** 2026-03-22

---

## Overview

Project Lumina uses a chmod-style permission model with 6 canonical roles. Permissions are stored as 3-digit octal values in each module's domain-physics document.

## Roles

| Role | ID | Hierarchy | Default Mode | Description |
|------|----|-----------|--------------|-------------|
| Root / OS Admin | `root` | 0 | 777 | Full system access, bypasses all permission checks |
| Domain Authority | `domain_authority` | 1 | 750 | Owns and manages domain pack modules |
| IT Support | `it_support` | 2 | 644 | System configuration and user management |
| Quality Assurance | `qa` | 2 | 644 | Evaluation access, read-only to modules |
| Auditor | `auditor` | 2 | 644 | System Log and compliance read access |
| Standard User | `user` | 3 | 644 | Session execution only |

## Permission Model

Each module declares a permission block in its domain-physics document:

```yaml
permissions:
  mode: "750"           # owner=rwx, group=r-x, others=---
  owner: "da_lead_001"  # pseudonymous ID of owning domain authority
  group: "domain_authority"
  acl:
    - role: qa
      access: rx
      scope: evaluation_only
    - role: auditor
      access: r
      scope: log_records_only
```

### Octal Notation

| Digit | Binary | Permissions |
|-------|--------|-------------|
| 7 | 111 | rwx (read + write + execute) |
| 6 | 110 | rw- (read + write) |
| 5 | 101 | r-x (read + execute) |
| 4 | 100 | r-- (read only) |
| 0 | 000 | --- (no access) |

### Friendly Display

The octal mode `750` displays as `rwxr-x---`:
- **Owner** (first 3): `rwx` — full access
- **Group** (middle 3): `r-x` — read and execute
- **Others** (last 3): `---` — no access

## Bootstrap Mode

When `LUMINA_BOOTSTRAP_MODE=true` (default), the first user to register is automatically assigned the `root` role. Subsequent users register as `user` by default.

Disable after initial setup:

```bash
export LUMINA_BOOTSTRAP_MODE=false
```

## Managing Users

Users are managed through the API:

```bash
# Register
curl -X POST /api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secure_pass_123", "role": "user"}'

# Login
curl -X POST /api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secure_pass_123"}'

# View profile
curl -H "Authorization: Bearer <token>" /api/auth/me

# List users (root/it_support only)
curl -H "Authorization: Bearer <token>" /api/auth/users
```

## Domain Authority Onboarding

Domain Authority accounts **must** be created via the invite flow — not self-registration — because they require `governed_modules` to be assigned at creation time. Root or IT Support issues the invite; the new DA activates their own account by following the setup link.

### Invite Flow Summary

```
root/it_support                           new Domain Authority
      │                                          │
      │──POST /api/auth/invite──────────────────►│  (setup_url returned)
      │  {username, role: domain_authority,       │
      │   governed_modules: [...]}                │
      │                                           │
      │  (optional: SMTP sends setup_url by email)│
      │                                           │
      │◄─────────────POST /api/auth/setup-password┤
      │         {token, new_password}              │
      │                                           │
      │  account activated → JWT returned ────────►
```

### Step-by-Step

```bash
# 1. Root issues invite (SMTP optional — setup_url is always returned in the response)
curl -X POST /api/auth/invite \
  -H "Authorization: Bearer <root-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "dr-chen",
    "role": "domain_authority",
    "governed_modules": ["domain/edu/algebra-level-1/v1"],
    "email": "dr.chen@example.com"
  }'
# Response includes: setup_url, setup_token, email_sent

# 2. DA visits setup_url and POSTs credentials
curl -X POST /api/auth/setup-password \
  -H "Content-Type: application/json" \
  -d '{"token": "<setup_token>", "new_password": "chosen-secure-pass"}'
# Response: {"access_token": "...", "token_type": "bearer"}
```

### Key Rules

- The invite token is **single-use** and expires after `LUMINA_INVITE_TOKEN_TTL_SECONDS` (default 24 h).
- The user record is marked `active=false` until the password is set. Authentication attempts on an inactive account return 403.
- `governed_modules` is **required** for `role: domain_authority` and must be a non-empty list of valid module IDs.
- SMTP delivery failure is non-blocking — the `setup_url` is always returned in the API response.
- The `invite_user` admin operation also triggers HITL staging (via `POST /api/admin/command`) so that an operator can approve DA creation before it executes. See [escalation-pin-unlock](./escalation-pin-unlock.md) for the staged-command resolve flow.

## Domain Role Management

Domain roles allow each domain to define its own access tiers beneath the Domain Authority ceiling. See [domain-role-hierarchy](../7-concepts/domain-role-hierarchy.md) for the full concept.

### Defining Domain Roles

Domain roles are declared in the `domain_roles` block of a domain-physics document. The Domain Authority authors these as part of the domain pack. Example for education:

```yaml
domain_roles:
  schema_version: "1.0"
  roles:
    - role_id: teacher
      role_name: Teacher
      hierarchy_level: 1
      maps_to_system_role: domain_authority
      default_access: rwx
      may_assign_domain_roles: true
      max_assignable_level: 2
    - role_id: teaching_assistant
      role_name: Teaching Assistant
      hierarchy_level: 2
      maps_to_system_role: user
      default_access: rx
    - role_id: student
      role_name: Student
      hierarchy_level: 3
      maps_to_system_role: user
      default_access: x
```

### Who Can Assign Domain Roles

- The **Domain Authority** (module owner) can assign any domain role
- Roles with `may_assign_domain_roles: true` can assign roles at or below their `max_assignable_level`
- All assignments are recorded as System Log `CommitmentRecord` entries (`commitment_type: domain_role_assignment`)

### Domain Role in JWT

When a user has domain roles, their JWT carries a `domain_roles` claim:

```json
{
  "sub": "user_ta_001",
  "role": "user",
  "domain_roles": {
    "domain/edu/algebra-level-1/v1": "teaching_assistant"
  }
}
```

## Manifest Integrity

The manifest integrity systools apply role-based restrictions separate from the module-level octal
permission model. These are system-level operations that act on `docs/MANIFEST.yaml` directly.

| Operation | API Endpoint | Permission | Allowed Roles |
|-----------|--------------|------------|---------------|
| Check integrity (read) | `GET /api/manifest/check` | Read (r) | `root`, `domain_authority`, `qa`, `auditor` |
| Regenerate hashes (write) | `POST /api/manifest/regen` | Write (w) | `root`, `domain_authority` |

The `auditor` role may inspect the manifest (read) but may **not** regenerate hashes (write). Regen
is a write operation that modifies `docs/MANIFEST.yaml` — it is restricted to roles with authoring
authority (`root` and `domain_authority`).

All `POST /api/manifest/regen` calls are recorded as a System Log `TraceEvent` on the `_admin` ledger for
full auditability.

From the command line, any authenticated user in an allowed role may also invoke the systools
directly:

```bash
# Check (auditor-accessible)
lumina-integrity-check
python -m lumina.systools.manifest_integrity check

# Regen (root / domain_authority only)
lumina-manifest-regen
python -m lumina.systools.manifest_integrity regen
```

## SEE ALSO

- [rbac-spec-v1](../../specs/rbac-spec-v1.md) — Full RBAC specification
- [auth(3)](../3-functions/auth.md) — JWT authentication module
- [permissions(3)](../3-functions/permissions.md) — Permission checker
- [domain-role-hierarchy](../7-concepts/domain-role-hierarchy.md) — Domain-scoped role hierarchy concept
- [domain-authority-roles](../../governance/domain-authority-roles.md) — Governance role definitions
