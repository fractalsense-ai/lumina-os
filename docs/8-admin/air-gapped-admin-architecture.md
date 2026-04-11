---
version: 1.0.0
last_updated: 2026-03-20
---

# Air-Gapped Admin Architecture

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-06-15  

---

## Overview

Project Lumina separates authentication into three parallel tracks:

| Track | Roles | JWT Issuer | Secret Env Var |
|-------|-------|-----------|----------------|
| **System** | root, it_support | `lumina-admin` | `LUMINA_ADMIN_JWT_SECRET` |
| **Domain** | domain_authority | `lumina-domain` | `LUMINA_DOMAIN_JWT_SECRET` |
| **User** | user, qa, auditor, guest | `lumina-user` | `LUMINA_USER_JWT_SECRET` |

Tokens from one track are cryptographically invalid on the others — each track uses a separate signing secret. This architectural separation is designed to evolve into full physical isolation (separate auth services per track, network boundaries) without application-level changes.

For the full design rationale and escalation prevention analysis, see [parallel-authority-tracks](../7-concepts/parallel-authority-tracks.md).

## Token Structure

Scoped tokens include a `token_scope` claim:

**System Track Token:**
```json
{
  "sub": "admin-001",
  "role": "root",
  "governed_modules": [],
  "iat": 1718438400,
  "exp": 1718442000,
  "iss": "lumina-admin",
  "jti": "...",
  "token_scope": "admin"
}
```

**Domain Track Token:**
```json
{
  "sub": "da-algebra-001",
  "role": "domain_authority",
  "governed_modules": ["domain/edu/algebra-level-1/v1"],
  "iat": 1718438400,
  "exp": 1718442000,
  "iss": "lumina-domain",
  "jti": "...",
  "token_scope": "domain"
}
```

**User Track Token:**
```json
{
  "sub": "user-student-042",
  "role": "user",
  "governed_modules": [],
  "iat": 1718438400,
  "exp": 1718442000,
  "iss": "lumina-user",
  "jti": "...",
  "token_scope": "user"
}
```

The `iss` claim distinguishes token provenance:
- `"lumina-admin"` — signed with `LUMINA_ADMIN_JWT_SECRET`
- `"lumina-domain"` — signed with `LUMINA_DOMAIN_JWT_SECRET`
- `"lumina-user"` — signed with `LUMINA_USER_JWT_SECRET`
- `"lumina"` — legacy token signed with `LUMINA_JWT_SECRET` (backward compat)

## Migration Path

1. **Phase 1 (current)** — Logical separation.  All three tracks run in the same FastAPI process.  When scoped secrets are not set, all functions fall back to the existing `LUMINA_JWT_SECRET`.  Existing tokens with `iss: "lumina"` continue to work — the scope is inferred from the role claim.

2. **Phase 2 (future)** — Physical separation.  Each track's auth routes move to a separate service behind a restricted network.  Tokens are validated by their track's auth service only.  The `iss` claim enables zero-config routing.

## API Endpoints

### System-Track Auth

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/admin/auth/login` | System-track login — requires root or it_support role |
| `POST` | `/api/admin/auth/refresh` | Refresh system-track token |
| `GET` | `/api/admin/auth/me` | System-track profile from token |

### Domain-Track Auth

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/domain/auth/login` | Domain-track login — requires domain_authority role |
| `POST` | `/api/domain/auth/refresh` | Refresh domain-track token |
| `GET` | `/api/domain/auth/me` | Domain-track profile from token |

### User-Track Auth (existing — unchanged)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/register` | Register new user |
| `POST` | `/api/auth/login` | User login |
| `GET` | `/api/auth/guest-token` | Issue guest token |
| `POST` | `/api/auth/refresh` | Refresh user token |
| `GET` | `/api/auth/me` | User profile |

## Middleware

| Function | Module | Purpose |
|----------|--------|---------|
| `get_admin_user()` | `admin_middleware.py` | Extract + verify admin-scoped token |
| `require_admin_auth()` | `admin_middleware.py` | Enforce admin scope (401/403) |
| `get_user_user()` | `admin_middleware.py` | Extract + verify user-scoped token |
| `require_user_auth()` | `admin_middleware.py` | Enforce user scope (401/403) |
| `get_current_user()` | `middleware.py` | Legacy — works with any valid token |
| `require_auth()` | `middleware.py` | Legacy — any authenticated user |

## Verification Strategy

When `verify_scoped_jwt()` receives a token:

1. **Decode payload** (without signature check) to read `iss`.
2. **Select secret** based on issuer:
   - `lumina-admin` → `LUMINA_ADMIN_JWT_SECRET` (fallback: `LUMINA_JWT_SECRET`)
   - `lumina-domain` → `LUMINA_DOMAIN_JWT_SECRET` (fallback: `LUMINA_JWT_SECRET`)
   - `lumina-user` → `LUMINA_USER_JWT_SECRET` (fallback: `LUMINA_JWT_SECRET`)
   - `lumina` → `LUMINA_JWT_SECRET` (legacy)
3. **Verify signature** with the selected secret.
4. **Check expiry** and **revocation** (same as legacy path).
5. **Enforce scope** if `required_scope` is specified.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LUMINA_JWT_SECRET` | Yes (fallback) | Legacy shared secret |
| `LUMINA_ADMIN_JWT_SECRET` | No | System-track signing secret |
| `LUMINA_DOMAIN_JWT_SECRET` | No | Domain-track signing secret |
| `LUMINA_USER_JWT_SECRET` | No | User-track signing secret |
| `LUMINA_JWT_TTL_MINUTES` | No (default: 60) | Token lifetime in minutes |

## Source Files

- `src/lumina/auth/auth.py` — `create_scoped_jwt()`, `verify_scoped_jwt()`, dual-secret config
- `src/lumina/api/admin_middleware.py` — Scope-aware auth helpers
- `src/lumina/api/routes/admin_auth.py` — Admin login/refresh/me endpoints
- `src/lumina/api/routes/auth.py` — Existing user auth endpoints (unchanged)
- `src/lumina/api/middleware.py` — Legacy middleware (unchanged, backward compat)
