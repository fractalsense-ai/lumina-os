---
section: 7
title: Parallel Authority Tracks
version: 1.0.0
last_updated: 2026-04-11
---

# Parallel Authority Tracks

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-04-11

---

## Summary

Root owns the system. Domain Authority owns their domain. Equal privilege within their
respective scope. The API is the only crossing point. No escalation path exists because
the tracks never merge.

## Problem

A hierarchical role ladder (root → domain_authority → it_support → user) creates an
implicit escalation pathway. If `domain_authority` is a rung on the same ladder as `root`,
the architecture allows — at least conceptually — for a role to be promoted up the chain.
Even with enforcement code preventing it, the *model* permits it. A department head and a
senior sysadmin hold equal authority in different scopes; one should never be able to become
the other.

## Design

Lumina replaces the single role hierarchy with **three parallel authority tracks**. Each track
has its own JWT signing secret, its own token issuer, and its own middleware enforcement.
Tokens from one track are cryptographically invalid on the others.

### Track Definitions

| Track | Roles | JWT Secret | Issuer | `token_scope` | Scope |
|-------|-------|------------|--------|---------------|-------|
| **System** | `root`, `it_support` | `LUMINA_ADMIN_JWT_SECRET` | `lumina-admin` | `"admin"` | Full system — all modules, all users, all configuration |
| **Domain** | `domain_authority` | `LUMINA_DOMAIN_JWT_SECRET` | `lumina-domain` | `"domain"` | Governed modules only — bounded by `governed_modules` JWT claim |
| **User** | `user`, `qa`, `auditor`, `guest` | `LUMINA_USER_JWT_SECRET` | `lumina-user` | `"user"` | Session-scoped — execute within assigned modules |

### Token Anatomy

**System Track Token**

```json
{
  "sub": "admin-001",
  "role": "root",
  "governed_modules": [],
  "iss": "lumina-admin",
  "token_scope": "admin",
  "iat": 1744300000,
  "exp": 1744303600,
  "jti": "a1b2c3d4..."
}
```

**Domain Track Token**

```json
{
  "sub": "da-algebra-001",
  "role": "domain_authority",
  "governed_modules": ["domain/edu/algebra-level-1/v1"],
  "iss": "lumina-domain",
  "token_scope": "domain",
  "iat": 1744300000,
  "exp": 1744303600,
  "jti": "e5f6g7h8..."
}
```

**User Track Token**

```json
{
  "sub": "user-student-042",
  "role": "user",
  "governed_modules": [],
  "domain_roles": {
    "domain/edu/algebra-level-1/v1": "student"
  },
  "iss": "lumina-user",
  "token_scope": "user",
  "iat": 1744300000,
  "exp": 1744303600,
  "jti": "i9j0k1l2..."
}
```

## Crossing Points

Tracks communicate only through explicitly defined API endpoints. Each crossing point
enforces scope at the boundary.

### Domain → System (read-only)

| Endpoint | Access | Scope Enforcement |
|----------|--------|-------------------|
| `GET /api/system-log/records` | DA reads log records | Filtered to DA's `governed_modules` only |
| `GET /api/domains` | DA lists registered domains | Returns metadata only, no write access |
| `GET /api/manifest/check` | DA checks manifest integrity | Read-only, no modification |

### System → Domain (administrative)

| Endpoint | Access | Scope Enforcement |
|----------|--------|-------------------|
| `POST /api/auth/invite` | Root creates DA accounts | Root assigns `governed_modules` at creation |
| `PATCH /api/auth/users/{id}` | Root modifies DA scope | Only root can change `governed_modules` |
| `GET /api/auth/users` | Root/IT lists all users | System track has full user visibility |

### Domain → Domain (mediated)

Domain-to-domain communication is always mediated through the API. A Domain Authority
for module A cannot directly access module B's physics or state. Cross-domain data flows
through:

1. **Escalation routing** — DA raises an escalation; the system routes it to the appropriate track.
2. **Domain-declared API routes** — Explicitly defined in `runtime-config.yaml` with role whitelisting.
3. **System Log records** — Shared audit trail readable by authorized roles within their scope.

## Escalation Prevention

### Why Escalation Is Architecturally Impossible

1. **Separate signing secrets.** A domain-track token is signed with `LUMINA_DOMAIN_JWT_SECRET`.
   The admin middleware verifies against `LUMINA_ADMIN_JWT_SECRET`. The signature will never match.
   Forging a valid system-track token requires knowing a secret the domain track never possesses.

2. **Issuer-based secret selection.** `verify_scoped_jwt()` reads the `iss` claim to select
   which secret to verify against. A token with `iss: "lumina-domain"` is always verified with
   the domain secret, never the admin secret. Changing the `iss` claim invalidates the signature.

3. **Scope enforcement at every endpoint.** System endpoints call `require_admin_auth()`, which
   rejects any token where `token_scope != "admin"`. Domain endpoints call `require_domain_auth()`,
   which rejects any token where `token_scope != "domain"`. There is no "any scope accepted" path
   for privileged operations.

4. **No role promotion pathway.** `domain_authority` is not in the system role enum. It exists
   only on the domain track. There is no API endpoint that accepts a domain-track token and
   returns a system-track token. The tracks do not share an identity store for role promotion.

5. **Governed modules boundary.** Even within the domain track, each DA is bounded by their
   `governed_modules` claim. DA for module A cannot author physics for module B. The middleware
   checks `governed_modules` on every domain-scoped write operation.

## Relationship to chmod Model

The octal permission model (`750`, `644`, etc.) operates *within* a track. Once a token is
verified and the track is established:

- **System track (root):** Bypasses all permission checks (unchanged).
- **Domain track (DA):** Resolves as owner for modules in `governed_modules`. Owner bits (first octal digit) apply. For modules outside `governed_modules`, access is denied outright — no fallback to group/others.
- **User track:** Resolves via group/others/ACL/domain-role as before. No change to the existing 7-step permission resolution.

## Configuration

### Environment Variables

```bash
# System track (root, it_support)
export LUMINA_ADMIN_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# Domain track (domain_authority)
export LUMINA_DOMAIN_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# User track (user, qa, auditor, guest)
export LUMINA_USER_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# Legacy fallback (backward compatibility during migration)
export LUMINA_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
```

All three scoped secrets should be distinct values. If any scoped secret is unset, the system
falls back to `LUMINA_JWT_SECRET` for that track. Production deployments should set all three.

## SEE ALSO

- [rbac-administration](../8-admin/rbac-administration.md) — RBAC administration guide
- [zero-trust-architecture](zero-trust-architecture.md) — Zero-trust enforcement layers
- [domain-role-hierarchy](domain-role-hierarchy.md) — Domain-scoped role hierarchy
- [domain-authority-roles](../8-admin/domain-authority-roles.md) — DA rights and obligations
- [auth(3)](../3-functions/auth.md) — JWT authentication module
