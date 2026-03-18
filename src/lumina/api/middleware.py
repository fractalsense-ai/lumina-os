"""Auth middleware: JWT extraction, require_auth, require_role."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from lumina.auth.auth import (
    AuthError,
    TokenExpiredError,
    TokenInvalidError,
    verify_jwt,
)

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = None,
) -> dict[str, Any] | None:
    """Extract and verify JWT from Authorization header.

    Returns the decoded token payload or None when no token is provided
    (allows endpoints to choose whether auth is required).
    """
    if credentials is None:
        return None
    try:
        payload = verify_jwt(credentials.credentials)
    except TokenExpiredError:
        raise HTTPException(status_code=401, detail="Token expired")
    except (TokenInvalidError, AuthError):
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload


def require_auth(user: dict[str, Any] | None) -> dict[str, Any]:
    """Raise 401 if no authenticated user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_role(user: dict[str, Any], *allowed_roles: str) -> None:
    """Raise 403 if user role is not in *allowed_roles*."""
    if user.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
