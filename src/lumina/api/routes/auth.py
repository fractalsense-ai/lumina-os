"""Auth endpoints: register, login, token management, user profile."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth, require_role
from lumina.api.models import (
    LoginRequest,
    PasswordResetRequest,
    RegisterRequest,
    RevokeRequest,
    TokenResponse,
    UpdateUserRequest,
    UserResponse,
)
from lumina.auth.auth import (
    VALID_ROLES,
    create_jwt,
    hash_password,
    revoke_token_jti,
    verify_password,
)
from lumina.ctl.admin_operations import (
    build_trace_event,
    can_govern_domain,
    map_role_to_actor_role,
)

log = logging.getLogger("lumina-api")

router = APIRouter()


@router.post("/api/auth/register", response_model=TokenResponse)
async def register(req: RegisterRequest) -> TokenResponse:
    if req.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {req.role}")

    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    existing = await run_in_threadpool(_cfg.PERSISTENCE.get_user_by_username, req.username)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already taken")

    all_users = await run_in_threadpool(_cfg.PERSISTENCE.list_users)
    role = req.role
    if _cfg.BOOTSTRAP_MODE and len(all_users) == 0:
        role = "root"
        log.info("Bootstrap mode: first user promoted to root")

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(req.password)

    await run_in_threadpool(
        _cfg.PERSISTENCE.create_user, user_id, req.username, pw_hash, role, req.governed_modules,
    )

    token = create_jwt(user_id=user_id, role=role, governed_modules=req.governed_modules or [])

    log.info("Registered user %s (%s) with role %s", req.username, user_id, role)
    return TokenResponse(access_token=token, user_id=user_id, role=role)


@router.post("/api/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = await run_in_threadpool(_cfg.PERSISTENCE.get_user_by_username, req.username)
    if user is None or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account deactivated")

    token = create_jwt(
        user_id=user["user_id"],
        role=user["role"],
        governed_modules=user.get("governed_modules") or [],
    )
    return TokenResponse(access_token=token, user_id=user["user_id"], role=user["role"])


@router.get("/api/auth/guest-token", response_model=TokenResponse)
async def guest_token() -> TokenResponse:
    guest_id = f"guest_{uuid.uuid4().hex[:12]}"
    token = create_jwt(user_id=guest_id, role="guest", governed_modules=[], ttl_minutes=30)
    return TokenResponse(access_token=token, user_id=guest_id, role="guest")


@router.post("/api/auth/refresh", response_model=TokenResponse)
async def refresh(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> TokenResponse:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    user = await run_in_threadpool(_cfg.PERSISTENCE.get_user, user_data["sub"])
    if user is None or not user.get("active", True):
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    token = create_jwt(
        user_id=user["user_id"],
        role=user["role"],
        governed_modules=user.get("governed_modules") or [],
    )
    return TokenResponse(access_token=token, user_id=user["user_id"], role=user["role"])


@router.get("/api/auth/me", response_model=UserResponse)
async def me(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UserResponse:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    user = await run_in_threadpool(_cfg.PERSISTENCE.get_user, user_data["sub"])
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        user_id=user["user_id"],
        username=user["username"],
        role=user["role"],
        governed_modules=user.get("governed_modules") or [],
        active=user.get("active", True),
    )


@router.get("/api/auth/users", response_model=list[UserResponse])
async def list_all_users(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[UserResponse]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root", "it_support")
    users = await run_in_threadpool(_cfg.PERSISTENCE.list_users)
    return [
        UserResponse(
            user_id=u["user_id"],
            username=u["username"],
            role=u["role"],
            governed_modules=u.get("governed_modules") or [],
            active=u.get("active", True),
        )
        for u in users
    ]


# ── User management (root only) ──


@router.patch("/api/auth/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UserResponse:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root")

    if req.role is not None and req.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {req.role}")

    if req.governed_modules is not None and req.role != "domain_authority":
        if req.role is not None:
            raise HTTPException(
                status_code=400,
                detail="governed_modules can only be set for domain_authority role",
            )

    target = await run_in_threadpool(_cfg.PERSISTENCE.get_user, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = target["role"]
    new_role = req.role or old_role
    new_governed = req.governed_modules if req.governed_modules is not None else target.get("governed_modules")

    updated = await run_in_threadpool(_cfg.PERSISTENCE.update_user_role, user_id, new_role, new_governed)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")

    if new_role != old_role:
        event = build_trace_event(
            session_id="admin",
            actor_id=user_data["sub"],
            event_type="other",
            decision=f"role_change: {old_role} -> {new_role}",
            evidence_summary={
                "target_user_id": user_id,
                "old_role": old_role,
                "new_role": new_role,
            },
        )
        try:
            _cfg.PERSISTENCE.append_ctl_record(
                "admin", event,
                ledger_path=_cfg.PERSISTENCE.get_ctl_ledger_path("admin", domain_id="_admin"),
            )
        except Exception:
            log.debug("Could not write role_change trace event")

    return UserResponse(
        user_id=updated["user_id"],
        username=updated["username"],
        role=updated["role"],
        governed_modules=updated.get("governed_modules") or [],
        active=updated.get("active", True),
    )


@router.delete("/api/auth/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root")

    if user_id == user_data["sub"]:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    success = await run_in_threadpool(_cfg.PERSISTENCE.deactivate_user, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")

    event = build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="other",
        decision="user_deactivated",
        evidence_summary={"target_user_id": user_id},
    )
    try:
        _cfg.PERSISTENCE.append_ctl_record(
            "admin", event,
            ledger_path=_cfg.PERSISTENCE.get_ctl_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write user_deactivated trace event")


@router.post("/api/auth/revoke", status_code=200)
async def revoke_token(
    req: RevokeRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, str]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if req.user_id is not None and req.user_id != user_data["sub"]:
        require_role(user_data, "root", "it_support")

    jti = user_data.get("jti")
    if jti:
        revoke_token_jti(jti)

    event = build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="other",
        decision="token_revoked",
        evidence_summary={"target_user_id": req.user_id or user_data["sub"]},
    )
    try:
        _cfg.PERSISTENCE.append_ctl_record(
            "admin", event,
            ledger_path=_cfg.PERSISTENCE.get_ctl_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write token_revoked trace event")

    return {"status": "revoked"}


@router.post("/api/auth/password-reset", status_code=200)
async def password_reset(
    req: PasswordResetRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, str]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    target_user_id = req.user_id or user_data["sub"]
    if target_user_id != user_data["sub"]:
        require_role(user_data, "root", "it_support")

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    new_hash = hash_password(req.new_password)
    success = await run_in_threadpool(_cfg.PERSISTENCE.update_user_password, target_user_id, new_hash)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")

    event = build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="other",
        decision="password_reset",
        evidence_summary={"target_user_id": target_user_id},
    )
    try:
        _cfg.PERSISTENCE.append_ctl_record(
            "admin", event,
            ledger_path=_cfg.PERSISTENCE.get_ctl_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write password_reset trace event")

    return {"status": "password_updated"}
