# Role-Based Access Control (RBAC) Specification — V1

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-09

---

## Overview

This specification defines the access control model for Project Lumina. The system uses a **chmod-style permission model** mapped to **role-based access control (RBAC)**. Permissions are stored internally as UNIX-style octal mode strings and presented to operators in a human-readable `rwx` format.

Every domain-pack module declares a `permissions` block that gates read, write, and execute access. The runtime enforces these permissions on every API request via JWT-authenticated identity and role claims.

---

## Roles

Lumina defines six canonical roles. Each role has a fixed position in the hierarchy and a default permission posture.

| Role | ID | Hierarchy | Description |
|------|----|-----------|-------------|
| **Root** | `root` | 0 (highest) | OS-level administrator. Full system access. Bypasses all permission checks. Manages users, roles, and system configuration. |
| **Domain Authority** | `domain_authority` | 1 | Subject-matter expert with authoring rights over governed modules. Scoped to specific domain packs. |
| **IT Support** | `it_support` | 2 | Tier-1 technical support. Diagnostics, session monitoring, and runtime troubleshooting. |
| **Quality Assurance** | `qa` | 2 | Test harness execution, conformance validation, and regression testing on assigned modules. |
| **Auditor** | `auditor` | 2 | Compliance and audit role. Read-only access to CTL records, audit logs, and session traces within scope. |
| **Standard User** | `user` | 3 (lowest) | End-user / session participant. May execute sessions on modules they are permitted to access. |

Hierarchy level determines tie-breaking and scope inheritance:

- A role at level $N$ may be granted access to resources governed by roles at level $N$ or below, subject to explicit permission grants.
- `root` (level 0) bypasses all checks — equivalent to the UNIX superuser.
- Roles at the same hierarchy level (e.g., `it_support`, `qa`, `auditor`) are peers with distinct default access patterns.

### Role Inheritance

Roles do **not** inherit permissions from other roles. Each role has its own default access pattern. However:

- A user with the `domain_authority` role inherits read access to modules governed by their Meta Authority chain (upward visibility for context).
- A user may hold exactly one role at any time. Role changes require a CTL `CommitmentRecord`.

---

## Permission Model

### Octal Mode

Each module declares a 3-digit octal permission mode, following UNIX conventions:

```
  u   g   o
  7   5   0
  rwx r-x ---
  │   │   └── others: no access
  │   └────── group: read + execute
  └────────── owner: full access
```

Each digit is the sum of:

| Bit | Value | Meaning |
|-----|-------|---------|
| r | 4 | **Read** — view domain physics, session data, CTL records, audit logs for this module |
| w | 2 | **Write** — author or modify the domain pack, standing orders, invariants, artifacts, subsystem configs |
| x | 1 | **Execute** — run sessions against this module, trigger tool adapters, invoke domain-lib functions |

### Owner / Group / Others

| Category | Resolution |
|----------|------------|
| **Owner (u)** | The user whose `pseudonymous_id` matches `permissions.owner` in the module's domain-physics |
| **Group (g)** | Any user whose `role` matches `permissions.group` in the module's domain-physics |
| **Others (o)** | Any authenticated user not matching owner or group |

### Default Modes by Role

These are the **recommended** defaults when a Domain Authority creates a new module. The actual mode is set explicitly in each module's domain-physics.

| Role Context | Default Mode | Symbolic | Rationale |
|-------------|-------------|----------|-----------|
| Domain Authority (owner) | `750` | `rwxr-x---` | Full access for owner; group members (other domain authorities) can read and execute; others denied |
| Shared module (cross-domain) | `755` | `rwxr-xr-x` | Owner full, group and others can read and execute |
| Restricted module (sensitive) | `700` | `rwx------` | Owner-only access |
| Open module (public training) | `755` | `rwxr-xr-x` | Broadly accessible |

### Permission Semantics by Operation

| API Operation | Required Permission | Rationale |
|---------------|-------------------|-----------|
| `POST /api/chat` | Execute (x) | Running a session executes the module's domain physics |
| `GET /api/domain-info` | Read (r) | Viewing module metadata is a read operation |
| `POST /api/tool/{tool_id}` | Execute (x) | Tool invocation is an execution within the session context |
| `GET /api/ctl/validate` | Read (r) | Viewing CTL integrity data is a read operation |
| Domain pack authoring | Write (w) | Creating or modifying domain-physics files |
| CTL record review | Read (r) | Audit trail inspection |

---

## Module Permission Block

Every domain-physics document must include a `permissions` block:

```yaml
permissions:
  mode: "750"
  owner: "da_algebra_lead_001"    # pseudonymous_id of the owning Domain Authority
  group: "domain_authority"       # role name that maps to the group bits
  acl:                            # optional extended ACL entries
    - role: qa
      access: rx                  # read + execute for QA testers
      scope: "evaluation_only"    # optional scope qualifier
    - role: auditor
      access: r                   # read-only for auditors
      scope: "ctl_records_only"
```

### Extended ACL

The `acl` array provides fine-grained overrides beyond the owner/group/others model:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | string | yes | One of the six canonical role IDs |
| `access` | string | yes | Combination of `r`, `w`, `x` characters |
| `scope` | string | no | Optional scope qualifier limiting what the access applies to. Values are module-defined (e.g., `evaluation_only`, `ctl_records_only`, `read_physics_only`). When omitted, access applies to the full module. |

ACL entries are evaluated **after** the octal mode check. An ACL entry can **grant** additional access not covered by the octal mode, but it cannot **revoke** access already granted by the mode bits.

---

## Permission Resolution Algorithm

For a given `(user, module, operation)` tuple:

```
1. If user.role == "root":  → ALLOW (bypass)

2. Determine category:
   a. If user.pseudonymous_id == module.permissions.owner  → category = OWNER
   b. Else if user.role == module.permissions.group        → category = GROUP
   c. Else                                                 → category = OTHERS

3. Extract bits from mode for the determined category:
   - OWNER → first octal digit
   - GROUP → second octal digit
   - OTHERS → third octal digit

4. Check if the required permission bit is set:
   - READ:    bit & 4 != 0
   - WRITE:   bit & 2 != 0
   - EXECUTE: bit & 1 != 0

5. If mode check grants access → ALLOW

6. Check ACL entries:
   For each entry where entry.role == user.role:
     If operation character in entry.access → ALLOW

7. → DENY
```

---

## Authentication

### JWT Claims

All authenticated requests carry a JWT in the `Authorization: Bearer <token>` header. The JWT payload contains:

```json
{
  "sub": "<pseudonymous_id>",
  "role": "domain_authority",
  "governed_modules": [
    "domain/edu/algebra-level-1/v1",
    "domain/edu/geometry-level-1/v1"
  ],
  "iat": 1741500000,
  "exp": 1741503600,
  "iss": "lumina"
}
```

| Claim | Type | Description |
|-------|------|-------------|
| `sub` | string | Pseudonymous user ID (32-character hex token). Matches `actor_id` in CTL records. |
| `role` | string | One of the six canonical role IDs |
| `governed_modules` | string[] | Module IDs this user has explicit governance over. Only meaningful for `domain_authority`; empty for other roles. |
| `iat` | integer | Issued-at timestamp (UNIX epoch) |
| `exp` | integer | Expiration timestamp (UNIX epoch) |
| `iss` | string | Issuer — always `"lumina"` for the built-in auth service |

### Token Lifecycle

1. **Registration** — `POST /api/auth/register` creates a user record. The first registered user receives the `root` role automatically (bootstrap mode). Subsequent registrations require an authenticated `root` or `domain_authority` caller.
2. **Login** — `POST /api/auth/login` validates credentials and returns an access token.
3. **Refresh** — `POST /api/auth/refresh` issues a new token before the current one expires.
4. **Revocation** — `POST /api/auth/revoke` invalidates a token. Only `root` or the token owner may revoke.
5. **Expiration** — tokens expire after `LUMINA_JWT_TTL_MINUTES` (default: 60 minutes).

### Bootstrap Mode

On first startup with no users in the system, `LUMINA_AUTH_BOOTSTRAP=true` (default) allows the first `POST /api/auth/register` call without authentication. This call creates the initial `root` user. Bootstrap mode auto-disables after the first `root` user is created.

---

## Domain Authority Scoping

A `domain_authority` user is scoped to specific modules via the `governed_modules` claim in their JWT:

- **Write** — only on modules listed in `governed_modules`
- **Read** — on governed modules plus modules governed by their Meta Authority chain (upward context visibility)
- **Execute** — on governed modules

An English teacher with `governed_modules: ["domain/edu/algebra-level-1/v1"]` cannot access `domain/edu/biology-level-1/v1` unless that module's ACL explicitly grants access.

### Module Isolation Example

```
domain/edu/algebra-level-1/v1
  permissions:
    mode: "750"
    owner: da_algebra_lead_001
    group: domain_authority

domain/edu/biology-level-1/v1
  permissions:
    mode: "750"
    owner: da_biology_lead_001
    group: domain_authority
```

User `da_algebra_lead_001`:
- algebra module: **OWNER** → rwx (full access) ✓
- biology module: **GROUP** (same role `domain_authority`) → r-x (read + execute) ✓
- biology module write: → **DENIED** (group has no write bit) ✗

This ensures subject-matter experts can observe peer modules but cannot modify them.

---

## CTL Integration

### Actor Identity in Records

All CTL records created during an authenticated session include the JWT-derived identity:

```json
{
  "record_type": "CommitmentRecord",
  "actor_id": "<from JWT sub claim>",
  "actor_role": "<from JWT role claim>",
  "commitment_type": "session_open",
  ...
}
```

### Role Change Auditing

When a user's role is changed (e.g., promoted from `user` to `domain_authority`), a `CommitmentRecord` is appended to the CTL:

```json
{
  "record_type": "CommitmentRecord",
  "actor_id": "<root user who made the change>",
  "actor_role": "root",
  "commitment_type": "role_change",
  "subject_id": "<user whose role changed>",
  "metadata": {
    "previous_role": "user",
    "new_role": "domain_authority",
    "governed_modules": ["domain/edu/algebra-level-1/v1"]
  }
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LUMINA_JWT_SECRET` | *(required in production)* | Signing key for JWT tokens |
| `LUMINA_JWT_TTL_MINUTES` | `60` | Token lifetime in minutes |
| `LUMINA_JWT_ALGORITHM` | `HS256` | JWT signing algorithm (`HS256` or `RS256`) |
| `LUMINA_AUTH_BOOTSTRAP` | `true` | Allow unauthenticated first-user registration |
| `LUMINA_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed CORS origins |

---

## Mapping to Governance Hierarchy

The six RBAC roles map to the existing four-level governance hierarchy:

| Governance Level | Governance Title | RBAC Role(s) | Notes |
|-----------------|-----------------|--------------|-------|
| 1 — Macro | School Board / Admin | `root` | Institution-wide system administration |
| 2 — Meso | Department Head | `domain_authority` (with Meta Authority scope) | Governs multiple modules and subordinate authorities |
| 3 — Micro | Teacher / Operator | `domain_authority` (with module scope) | Governs specific modules |
| 4 — Subject | Student / Patient | `user` | Session participant |
| (cross-cutting) | IT Support | `it_support` | Technical operations across domains |
| (cross-cutting) | QA Tester | `qa` | Conformance testing across assigned modules |
| (cross-cutting) | Compliance Officer | `auditor` | Audit trail review within scope |

---

## References

- [`rbac-permission-schema-v1.json`](../standards/rbac-permission-schema-v1.json) — JSON schema for module permission blocks
- [`role-definition-schema-v1.json`](../standards/role-definition-schema-v1.json) — JSON schema for role records
- [`domain-authority-roles.md`](../governance/domain-authority-roles.md) — Domain Authority governance definitions
- [`meta-authority-policy-template.yaml`](../governance/meta-authority-policy-template.yaml) — Meta Authority policy template
- [`lumina-core-v1.md`](../standards/lumina-core-v1.md) — core conformance requirements
