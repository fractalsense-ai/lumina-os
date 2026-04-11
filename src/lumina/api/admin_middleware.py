"""Admin middleware — scope-aware auth for air-gapped admin/user separation.

Provides ``require_admin_auth`` and ``require_user_auth`` helpers that
verify tokens using the *scoped* verification path and enforce that the
token belongs to the correct tier.

Domain-track tokens (``token_scope: "domain"``) are explicitly rejected
by both functions.  Domain authorities use the domain middleware instead.

See docs/7-concepts/parallel-authority-tracks.md for the three-track design.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from lumina.auth.auth import (
    AuthError,
    TokenExpiredError,
    TokenInvalidError,
    verify_scoped_jwt,
)

_admin_bearer = HTTPBearer(auto_error=False)
_user_bearer = HTTPBearer(auto_error=False)


async def get_admin_user(
    credentials: HTTPAuthorizationCredentials | None = None,
) -> dict[str, Any] | None:
    """Extract, verify, and scope-check an admin token."""
    if credentials is None:
        return None
    try:
        return verify_scoped_jwt(credentials.credentials, required_scope="admin")
    except TokenExpiredError:
        raise HTTPException(status_code=401, detail="Token expired")
    except (TokenInvalidError, AuthError):
        raise HTTPException(status_code=401, detail="Invalid or non-admin token")


async def get_user_user(
    credentials: HTTPAuthorizationCredentials | None = None,
) -> dict[str, Any] | None:
    """Extract, verify, and scope-check a user-tier token."""
    if credentials is None:
        return None
    try:
        return verify_scoped_jwt(credentials.credentials, required_scope="user")
    except TokenExpiredError:
        raise HTTPException(status_code=401, detail="Token expired")
    except (TokenInvalidError, AuthError):
        raise HTTPException(status_code=401, detail="Invalid or non-user token")


def require_admin_auth(user: dict[str, Any] | None) -> dict[str, Any]:
    """Raise 401 if no authenticated admin-tier user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    if user.get("token_scope") != "admin":
        raise HTTPException(status_code=403, detail="Admin token required")
    return user


def require_user_auth(user: dict[str, Any] | None) -> dict[str, Any]:
    """Raise 401 if no authenticated user-tier user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.get("token_scope") != "user":
        raise HTTPException(status_code=403, detail="User token required")
    return user
