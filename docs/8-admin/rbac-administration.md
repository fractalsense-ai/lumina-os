---
version: 1.1.0
last_updated: 2026-04-11
---

# RBAC Administration

**Version:** 1.3.0
**Status:** Active
**Last updated:** 2026-04-11

---

## Overview

Project Lumina uses a chmod-style permission model organized into **three
parallel authority tracks**.  Each track has its own JWT signing secret,
issuer, and login endpoint.  The tracks do not share escalation paths.
See [parallel-authority-tracks](../7-concepts/parallel-authority-tracks.md)
for the full concept.

## Authority Tracks

| Track | Roles | JWT Issuer | Login Endpoint |
|-------|-------|------------|----------------|
| **System** | `root`, `super_admin` | `lumina-admin` | `POST /api/admin/auth/login` |
| **Domain** | `admin` | `lumina-domain` | `POST /api/domain/auth/login` |
| **User** | `user`, `operator`, `half_operator`, `guest` | `lumina-user` | `POST /api/auth/login` |

## Roles

| Role | ID | Track | Default Mode | Description |
|------|----|-------|--------------|-------------|
| Root / OS Admin | `root` | System | 777 | Full system access, bypasses all permission checks |
| IT Support | `super_admin` | System | 644 | System configuration and user management |
| Domain Authority | `admin` | Domain | 750 | Owns and manages domain pack modules within governed_modules |
| Quality Assurance | `operator` | User | 644 | Evaluation access, read-only to modules |
| half_operator | `half_operator` | User | 644 | System Log and compliance read access |
| Standard User | `user` | User | 644 | Session execution only |

## Permission Model

Each module declares a permission block in its domain-physics document:

```yaml
permissions:
  mode: "750"           # owner=rwx, group=r-x, others=---
  owner: "da_lead_001"  # pseudonymous ID of owning domain authority
  group: "educators"    # references a named group defined in the groups block
  acl:
    - role: operator
      access: rx
      scope: evaluation_only
    - role: half_operator
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

## Groups

The `groups` block in a domain-physics document defines named groups for chmod-style group permission resolution — analogous to `/etc/group` in UNIX. The kernel resolves group membership at runtime by checking the user's system role or domain role against the `members` block; it never interprets the group name semantically.

```yaml
groups:
  educators:
    description: "Teaching staff with group-level permissions."
    members:
      domain_roles: [teacher, teaching_assistant]
  learners:
    description: "Students enrolled in the module."
    members:
      domain_roles: [student]
```

Each group entry has:
- **`members.system_roles`** — list of system role IDs whose holders are members.
- **`members.domain_roles`** — list of domain role IDs whose holders are members.
- At least one of the two lists must be present.

The `permissions.group` field references a group name. When the kernel evaluates the group permission bits (middle octal digit), it checks whether the requesting user is a member of the named group.

**Backward compatibility:** If no `groups` block exists, or the group name is not defined in it, the kernel falls back to matching `permissions.group` literally against the user's system role — the pre-groups behavior.

## Bootstrap Mode

When `LUMINA_BOOTSTRAP_MODE=true` (default), the first user to register is automatically assigned the `root` role. Subsequent users register as `user` by default.

Disable after initial setup:

```bash
export LUMINA_BOOTSTRAP_MODE=false
```

## Managing Users

Users are managed through track-specific API endpoints:

```bash
# Register (user track only — admin/domain accounts use the invite flow)
curl -X POST /api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secure_pass_123", "role": "user"}'

# Login — each track has its own endpoint
curl -X POST /api/auth/login         # user track
curl -X POST /api/admin/auth/login   # system track (root, super_admin)
curl -X POST /api/domain/auth/login  # domain track (admin)

# View profile — use the endpoint matching your track
curl -H "Authorization: Bearer <token>" /api/auth/me           # user
curl -H "Authorization: Bearer <token>" /api/admin/auth/me     # system
curl -H "Authorization: Bearer <token>" /api/domain/auth/me    # domain

# List users (root/super_admin only — system track)
curl -H "Authorization: Bearer <admin-token>" /api/auth/users
```

> **Track enforcement:** Attempting to log in on the wrong track returns
> 403 with a message indicating the correct endpoint.

## Domain Authority Onboarding

Domain Authority accounts **must** be created via the invite flow — not self-registration — because they require `governed_modules` to be assigned at creation time. Root or IT Support issues the invite; the new DA activates their own account by following the setup link.

### Invite Flow Summary

```
root/super_admin                           new Domain Authority
      │                                          │
      │──POST /api/auth/invite──────────────────►│  (setup_url returned)
      │  {username, role: admin,       │
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
    "role": "admin",
    "governed_modules": ["domain/edu/algebra-level-1/v1"],
    "email": "dr.chen@example.com"
  }'
# Response includes: setup_url, setup_token, email_sent

# 2. DA visits setup_url and POSTs credentials
curl -X POST /api/auth/setup-password \
  -H "Content-Type: application/json" \
  -d '{"token": "<setup_token>", "new_password": "chosen-secure-pass"}'
# Response: {"access_token": "...", "token_type": "bearer"}
# NOTE: The returned token is domain-scoped (iss: lumina-domain).
# Subsequent logins must use POST /api/domain/auth/login.
```

### Key Rules

- The invite token is **single-use** and expires after `LUMINA_INVITE_TOKEN_TTL_SECONDS` (default 24 h).
- The user record is marked `active=false` until the password is set. Authentication attempts on an inactive account return 403.
- `governed_modules` is **required** for `role: admin` and must be a non-empty list of valid module IDs.
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
      maps_to_system_role: user
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
| Check integrity (read) | `GET /api/manifest/check` | Read (r) | `root`, `admin`, `operator`, `half_operator` |
| Regenerate hashes (write) | `POST /api/manifest/regen` | Write (w) | `root`, `admin` |

The `half_operator` role may inspect the manifest (read) but may **not** regenerate hashes (write). Regen
is a write operation that modifies `docs/MANIFEST.yaml` — it is restricted to roles with authoring
authority (`root` and `admin`).

All `POST /api/manifest/regen` calls are recorded as a System Log `TraceEvent` on the `_admin` ledger for
full auditability.

From the command line, any authenticated user in an allowed role may also invoke the systools
directly:

```bash
# Check (half_operator-accessible)
lumina-integrity-check
python -m lumina.systools.manifest_integrity check

# Regen (root / admin only)
lumina-manifest-regen
python -m lumina.systools.manifest_integrity regen
```

## Discovery Operations

Two HITL-exempt admin operations allow querying the domain and module
inventory without HITL staging:

| Operation       | Command                      | RBAC                                |
|----------------|------------------------------|-------------------------------------|
| `list_domains`  | "list domains"               | root, admin, super_admin  |
| `list_modules`  | "list modules for education" | root, admin*, super_admin |

\* Domain Authority sees only modules for domains they govern.

These execute immediately and return results inline. See
[list-domains(1)](../1-commands/list-domains.md) and
[list-modules(1)](../1-commands/list-modules.md).

## DA-Scoped User Invites

A Domain Authority can invite new users into their governed modules,
subject to these constraints:

- The invited user's role must be `user` or `guest` (DA cannot create
  higher-privileged system accounts).
- The `governed_modules` of the new user must be a subset of the DA's
  own `governed_modules`.
- The invite follows the same HITL staging flow as root invites.

This allows DAs to onboard students, TAs, and parents without escalating
to root for every new user.

## Escalation Resolution by Domain Role

Users with a domain role that has `receive_escalations: true` in their
module's domain-physics can resolve escalations for that module.  This
extends the default RBAC check (which allows only `root` and
`admin`) to include teachers and other instructional staff.

The resolution is scoped: the user can only resolve escalations whose
`model_pack_id` matches a module where they hold an escalation-capable
domain role.

## SEE ALSO

- [parallel-authority-tracks](../7-concepts/parallel-authority-tracks.md) — Three-track authority model concept
- [rbac-spec-v1](../../specs/rbac-spec-v1.md) — Full RBAC specification
- [auth(3)](../3-functions/auth.md) — JWT authentication module
- [permissions(3)](../3-functions/permissions.md) — Permission checker
- [domain-role-hierarchy](../7-concepts/domain-role-hierarchy.md) — Domain-scoped role hierarchy concept
- [domain-authority-roles](../../governance/domain-authority-roles.md) — Governance role definitions
- [list-domains(1)](../1-commands/list-domains.md) — List registered domains
- [list-modules(1)](../1-commands/list-modules.md) — List modules for a domain
- [graceful-degradation](../7-concepts/graceful-degradation.md) — Clarification flow for SLM failures
