"""Admin and domain auth endpoints — separate login/refresh per authority track.

This router provides air-gapped authentication endpoints for:
- System-level users (root, it_support) via ``/api/admin/auth/*``
- Domain authorities via ``/api/domain/auth/*``

System tokens carry ``iss: "lumina-admin"`` and ``token_scope: "admin"``.
Domain tokens carry ``iss: "lumina-domain"`` and ``token_scope: "domain"``.

The two tracks use separate signing secrets and neither can access the
other's endpoints.  See docs/7-concepts/parallel-authority-tracks.md.

End-user auth continues to use ``/api/auth/*`` (routes/auth.py).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.admin_middleware import (
    _admin_bearer,
    get_admin_user,
    require_admin_auth,
)
from lumina.api.domain_middleware import (
    _domain_bearer,
    get_domain_user,
    require_domain_auth,
)
from lumina.api.models import LoginRequest, TokenResponse
from lumina.auth.auth import (
    ADMIN_ROLES,
    DOMAIN_AUTHORITY_ROLES,
    create_scoped_jwt,
    verify_password,
)

log = logging.getLogger("lumina-api")

router = APIRouter()


@router.post("/api/admin/auth/login", response_model=TokenResponse)
async def admin_login(req: LoginRequest) -> TokenResponse:
    """Authenticate a system-track user and issue a scoped admin token.

    Only ``root`` and ``it_support`` may use this endpoint.
    Domain authorities must use ``/api/domain/auth/login`` instead.
    """
    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = await run_in_threadpool(_cfg.PERSISTENCE.get_user_by_username, req.username)
    if user is None or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account deactivated")

    if user["role"] not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Admin login requires a system-track role (root, it_support)",
        )

    token = create_scoped_jwt(
        user_id=user["user_id"],
        role=user["role"],
        governed_modules=user.get("governed_modules") or [],
        domain_roles=user.get("domain_roles") or {},
    )
    return TokenResponse(access_token=token, user_id=user["user_id"], role=user["role"])


@router.post("/api/admin/auth/refresh", response_model=TokenResponse)
async def admin_refresh(
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),
) -> TokenResponse:
    """Refresh an admin token.  Requires a valid admin-scoped token."""
    current = await get_admin_user(credentials)
    user_data = require_admin_auth(current)

    user = await run_in_threadpool(_cfg.PERSISTENCE.get_user, user_data["sub"])
    if user is None or not user.get("active", True):
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    if user["role"] not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="User is no longer a system-track role")

    token = create_scoped_jwt(
        user_id=user["user_id"],
        role=user["role"],
        governed_modules=user.get("governed_modules") or [],
        domain_roles=user.get("domain_roles") or {},
    )
    return TokenResponse(access_token=token, user_id=user["user_id"], role=user["role"])


@router.get("/api/admin/auth/me")
async def admin_me(
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),
) -> dict[str, Any]:
    """Return admin profile extracted from a valid admin token."""
    current = await get_admin_user(credentials)
    user_data = require_admin_auth(current)
    return {
        "user_id": user_data["sub"],
        "role": user_data["role"],
        "token_scope": user_data.get("token_scope", "admin"),
        "governed_modules": user_data.get("governed_modules", []),
    }


# ── Domain-track endpoints ──────────────────────────────────────────────


@router.post("/api/domain/auth/login", response_model=TokenResponse)
async def domain_login(req: LoginRequest) -> TokenResponse:
    """Authenticate a domain authority and issue a domain-scoped token.

    Only users with the ``domain_authority`` role may use this endpoint.
    System-track users must use ``/api/admin/auth/login``;
    regular users must use ``/api/auth/login``.
    """
    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = await run_in_threadpool(_cfg.PERSISTENCE.get_user_by_username, req.username)
    if user is None or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account deactivated")

    if user["role"] not in DOMAIN_AUTHORITY_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Domain login requires the domain_authority role",
        )

    token = create_scoped_jwt(
        user_id=user["user_id"],
        role=user["role"],
        governed_modules=user.get("governed_modules") or [],
        domain_roles=user.get("domain_roles") or {},
    )
    return TokenResponse(access_token=token, user_id=user["user_id"], role=user["role"])


@router.post("/api/domain/auth/refresh", response_model=TokenResponse)
async def domain_refresh(
    credentials: HTTPAuthorizationCredentials | None = Depends(_domain_bearer),
) -> TokenResponse:
    """Refresh a domain-scoped token.  Requires a valid domain token."""
    current = await get_domain_user(credentials)
    user_data = require_domain_auth(current)

    user = await run_in_threadpool(_cfg.PERSISTENCE.get_user, user_data["sub"])
    if user is None or not user.get("active", True):
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    if user["role"] not in DOMAIN_AUTHORITY_ROLES:
        raise HTTPException(status_code=403, detail="User is no longer a domain authority")

    token = create_scoped_jwt(
        user_id=user["user_id"],
        role=user["role"],
        governed_modules=user.get("governed_modules") or [],
        domain_roles=user.get("domain_roles") or {},
    )
    return TokenResponse(access_token=token, user_id=user["user_id"], role=user["role"])


@router.get("/api/domain/auth/me")
async def domain_me(
    credentials: HTTPAuthorizationCredentials | None = Depends(_domain_bearer),
) -> dict[str, Any]:
    """Return domain-authority profile from a valid domain token."""
    current = await get_domain_user(credentials)
    user_data = require_domain_auth(current)
    return {
        "user_id": user_data["sub"],
        "role": user_data["role"],
        "token_scope": user_data.get("token_scope", "domain"),
        "governed_modules": user_data.get("governed_modules", []),
    }
