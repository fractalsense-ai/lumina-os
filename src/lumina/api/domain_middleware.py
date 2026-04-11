"""Domain middleware — scope-aware auth for domain authority track.

Provides ``require_domain_auth`` and ``require_domain_scope`` helpers that
verify tokens signed with ``LUMINA_DOMAIN_JWT_SECRET`` and enforce that the
caller is a domain authority operating within their governed modules.

Domain-track tokens carry ``token_scope: "domain"`` and ``iss: "lumina-domain"``.
They have NO pathway to system (admin) endpoints.

See docs/7-concepts/parallel-authority-tracks.md for the design.
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

_domain_bearer = HTTPBearer(auto_error=False)


async def get_domain_user(
    credentials: HTTPAuthorizationCredentials | None = None,
) -> dict[str, Any] | None:
    """Extract, verify, and scope-check a domain-track token."""
    if credentials is None:
        return None
    try:
        return verify_scoped_jwt(credentials.credentials, required_scope="domain")
    except TokenExpiredError:
        raise HTTPException(status_code=401, detail="Token expired")
    except (TokenInvalidError, AuthError):
        raise HTTPException(status_code=401, detail="Invalid or non-domain token")


def require_domain_auth(user: dict[str, Any] | None) -> dict[str, Any]:
    """Raise 401/403 if no authenticated domain-track user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Domain authentication required")
    if user.get("token_scope") != "domain":
        raise HTTPException(status_code=403, detail="Domain token required")
    return user


def require_domain_scope(user: dict[str, Any], module_id: str) -> None:
    """Raise 403 if the domain authority does not govern *module_id*.

    The ``governed_modules`` claim in the JWT lists the modules this DA owns.
    Access to any module outside that list is denied outright — no fallback.
    """
    governed = user.get("governed_modules") or []
    if not governed:
        raise HTTPException(
            status_code=403,
            detail="Domain authority has no governed modules",
        )
    if module_id not in governed:
        raise HTTPException(
            status_code=403,
            detail=f"Module {module_id!r} is outside governed scope",
        )
