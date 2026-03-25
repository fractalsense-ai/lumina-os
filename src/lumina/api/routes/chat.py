"""POST /api/chat — domain-resolved chat endpoint."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user
from lumina.api.models import ChatRequest, ChatResponse
from lumina.api.processing import process_message
from lumina.core.domain_registry import DomainNotFoundError
from lumina.core.permissions import Operation, check_permission
from lumina.system_log.commit_guard import requires_log_commit

log = logging.getLogger("lumina-api")

router = APIRouter()


def _get_accessible_domain_ids(
    user: dict[str, Any],
    routing_map: dict[str, dict[str, Any]],
) -> list[str]:
    """Return domain IDs the user has EXECUTE access to."""
    if user.get("role") == "root":
        return list(routing_map.keys())

    accessible: list[str] = []
    for domain_id in routing_map:
        try:
            runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(domain_id)
            domain_physics_path = runtime["domain_physics_path"]
            domain = _cfg.PERSISTENCE.load_domain_physics(str(domain_physics_path))
            module_perms = domain.get("permissions")
            if module_perms is None:
                accessible.append(domain_id)
                continue
            if check_permission(
                user_id=user["sub"],
                user_role=user["role"],
                module_permissions=module_perms,
                operation=Operation.EXECUTE,
                groups_config=domain.get("groups"),
            ):
                accessible.append(domain_id)
        except Exception:
            continue
    return accessible


@router.post("/api/chat", response_model=ChatResponse)
@requires_log_commit
async def chat(
    req: ChatRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    user = await get_current_user(credentials)

    # ── Domain resolution: semantic routing → explicit → default ──
    routing_record: dict[str, Any] = {
        "event": "routing_decision",
        "explicit_domain": req.domain_id,
        "session_id": session_id,
        "timestamp": time.time(),
    }

    if req.domain_id:
        try:
            resolved_domain_id = _cfg.DOMAIN_REGISTRY.resolve_domain_id(req.domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        routing_record["method"] = "explicit"
        routing_record["confidence"] = 1.0
    else:
        try:
            from core_nlp import classify_domain
        except ImportError:
            classify_domain = None  # type: ignore[assignment]

        routing_map = _cfg.DOMAIN_REGISTRY.get_domain_routing_map()
        inferred = None

        if classify_domain is not None and routing_map:
            accessible = None
            if user is not None:
                accessible = _get_accessible_domain_ids(user, routing_map)
            inferred = classify_domain(req.message, routing_map, accessible)

        if inferred is not None:
            resolved_domain_id = inferred["domain_id"]
            routing_record["method"] = inferred.get("method", "keyword")
            routing_record["confidence"] = inferred["confidence"]
            routing_record["inferred_domain"] = inferred["domain_id"]
            log.info(
                "[%s] Semantic routing: %s (confidence=%.3f, method=%s)",
                session_id,
                resolved_domain_id,
                inferred["confidence"],
                inferred.get("method"),
            )
        else:
            try:
                resolved_domain_id = _cfg.DOMAIN_REGISTRY.resolve_default_for_user(user)
            except RuntimeError:
                raise HTTPException(
                    status_code=400,
                    detail="Could not determine domain. Please specify domain_id.",
                )
            routing_record["method"] = "role_default"
            routing_record["confidence"] = 0.0
            log.info(
                "[%s] Role-based default routing: %s (role=%s)",
                session_id,
                resolved_domain_id,
                user.get("role") if user else "unauthenticated",
            )

    routing_record["final_domain"] = resolved_domain_id

    # ── RBAC gate ──
    if user is not None:
        runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved_domain_id)
        domain_physics_path = runtime["domain_physics_path"]
        domain = await run_in_threadpool(_cfg.PERSISTENCE.load_domain_physics, str(domain_physics_path))
        module_perms = domain.get("permissions")
        if module_perms:
            has_access = check_permission(
                user_id=user["sub"],
                user_role=user["role"],
                module_permissions=module_perms,
                operation=Operation.EXECUTE,
                groups_config=domain.get("groups"),
            )
            if not has_access:
                raise HTTPException(status_code=403, detail="Module access denied")

    # ── Log routing decision to meta-ledger ──
    try:
        _cfg.PERSISTENCE.append_log_record(
            session_id,
            routing_record,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path(session_id, domain_id="_meta"),
        )
    except Exception:
        log.debug("Could not write routing decision to meta-ledger")

    try:
        result = await run_in_threadpool(
            process_message,
            session_id,
            req.message,
            req.turn_data_override,
            req.deterministic_response,
            resolved_domain_id,
            user,
            req.model_id,
            req.model_version,
        )
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "policy commitment" in msg:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Domain physics have been modified but not yet committed. "
                    "An administrator must run 'commit domain physics' before "
                    "this module can accept conversations."
                ),
            )
        if "system-physics commitment" in msg or "system_physics" in msg:
            raise HTTPException(
                status_code=503,
                detail=(
                    "System physics are not yet committed. "
                    "The system administrator must commit the current "
                    "system-physics.json before the service is available."
                ),
            )
        log.exception("RuntimeError processing message for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        log.exception("Error processing message for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(
        session_id=session_id,
        response=result["response"],
        action=result["action"],
        prompt_type=result["prompt_type"],
        escalated=result["escalated"],
        tool_results=result.get("tool_results") or None,
        domain_id=result.get("domain_id"),
        structured_content=result.get("structured_content"),
    )
