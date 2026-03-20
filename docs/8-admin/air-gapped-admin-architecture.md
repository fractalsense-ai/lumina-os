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

Project Lumina separates authentication into two tiers:

| Tier | Roles | JWT Issuer | Secret Env Var |
|------|-------|-----------|----------------|
| **Admin** | root, domain_authority, it_support | `lumina-admin` | `LUMINA_ADMIN_JWT_SECRET` |
| **User** | user, qa, auditor, guest | `lumina-user` | `LUMINA_USER_JWT_SECRET` |

Admin tokens cannot access user-only endpoints and vice-versa.  This architectural separation is designed to evolve into full physical isolation (separate auth service, network boundary) without application-level changes.

## Token Structure

Scoped tokens include a `token_scope` claim:

```json
{
  "sub": "user-uuid",
  "role": "domain_authority",
  "governed_modules": ["algebra-level-1/v1"],
  "iat": 1718438400,
  "exp": 1718442000,
  "iss": "lumina-admin",
  "jti": "...",
  "token_scope": "admin"
}
```

The `iss` claim distinguishes token provenance:
- `"lumina-admin"` — signed with `LUMINA_ADMIN_JWT_SECRET`
- `"lumina-user"` — signed with `LUMINA_USER_JWT_SECRET`
- `"lumina"` — legacy token signed with `LUMINA_JWT_SECRET` (backward compat)

## Migration Path

1. **Phase 1 (current)** — Logical separation.  Both tiers run in the same FastAPI process.  When `LUMINA_ADMIN_JWT_SECRET` and `LUMINA_USER_JWT_SECRET` are not set, all functions fall back to the existing `LUMINA_JWT_SECRET`.  Existing tokens with `iss: "lumina"` continue to work — the scope is inferred from the role claim.

2. **Phase 2 (future)** — Physical separation.  Admin auth routes move to a separate service behind a restricted network.  Admin tokens are validated by the admin auth service only.  The `iss` claim enables zero-config routing.

## API Endpoints

### Admin Auth (new)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/admin/auth/login` | Admin login — requires admin-tier role |
| `POST` | `/api/admin/auth/refresh` | Refresh admin token |
| `GET` | `/api/admin/auth/me` | Admin profile from token |

### User Auth (existing — unchanged)

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
   - `lumina-user` → `LUMINA_USER_JWT_SECRET` (fallback: `LUMINA_JWT_SECRET`)
   - `lumina` → `LUMINA_JWT_SECRET` (legacy)
3. **Verify signature** with the selected secret.
4. **Check expiry** and **revocation** (same as legacy path).
5. **Enforce scope** if `required_scope` is specified.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LUMINA_JWT_SECRET` | Yes (fallback) | Legacy shared secret |
| `LUMINA_ADMIN_JWT_SECRET` | No | Admin-tier signing secret |
| `LUMINA_USER_JWT_SECRET` | No | User-tier signing secret |
| `LUMINA_JWT_TTL_MINUTES` | No (default: 60) | Token lifetime in minutes |

## Source Files

- `src/lumina/auth/auth.py` — `create_scoped_jwt()`, `verify_scoped_jwt()`, dual-secret config
- `src/lumina/api/admin_middleware.py` — Scope-aware auth helpers
- `src/lumina/api/routes/admin_auth.py` — Admin login/refresh/me endpoints
- `src/lumina/api/routes/auth.py` — Existing user auth endpoints (unchanged)
- `src/lumina/api/middleware.py` — Legacy middleware (unchanged, backward compat)
