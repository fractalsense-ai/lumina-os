# auth(3)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`auth.py` — JWT authentication and password hashing

## SYNOPSIS

```python
from auth import create_jwt, verify_jwt, hash_password, verify_password
```

## FUNCTIONS

### `create_jwt(user_id, role, governed_modules, ttl_minutes=None) → str`

Create a signed JWT containing user identity and RBAC claims.

**Claims:** `sub` (user_id), `role`, `governed_modules`, `iss` ("lumina"), `iat`, `exp`

### `verify_jwt(token) → dict`

Decode and verify a JWT. Returns the payload dict.

**Raises:** `TokenExpiredError`, `TokenInvalidError`

### `hash_password(password) → str`

Hash a password with a random salt. Returns `"salt:hash"` string.

### `verify_password(password, stored) → bool`

Verify a password against a stored `"salt:hash"` string.

## CONSTANTS

- `VALID_ROLES` — `frozenset({"root", "domain_authority", "it_support", "qa", "auditor", "user"})`

## EXCEPTIONS

- `AuthError` — Base authentication exception
- `TokenExpiredError(AuthError)` — JWT has expired
- `TokenInvalidError(AuthError)` — JWT signature or structure is invalid

## ENVIRONMENT

| Variable | Default | Description |
|----------|---------|-------------|
| `LUMINA_JWT_SECRET` | — | HMAC signing key (required for production) |
| `LUMINA_JWT_TTL_MINUTES` | `60` | Token time-to-live in minutes |
| `LUMINA_JWT_ALGORITHM` | `HS256` | JWT signing algorithm |

## NOTES

This module uses zero external dependencies — JWT is implemented using the standard library (`hmac`, `hashlib`, `base64`). Production deployments should evaluate an external IdP.

## SEE ALSO

[permissions(3)](permissions.md), [rbac-spec](../../specs/rbac-spec-v1.md)
