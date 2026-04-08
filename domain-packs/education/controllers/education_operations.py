"""Education domain operation handlers for the admin command pipeline.

Each handler follows the domain-pack handler signature:

    async def handler(operation, params, user_data, ctx) -> dict

This module is loaded dynamically by the admin operation handler registry
via ``runtime-config.yaml → operation_handlers``.

See docs/7-concepts/command-execution-pipeline.md
See docs/7-concepts/domain-adapter-pattern.md
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("lumina.education-ops")


# ─────────────────────────────────────────────────────────────
# TA ↔ teacher student-roster sync helper
# ─────────────────────────────────────────────────────────────

async def _sync_ta_students(
    teacher_id: str,
    student_id: str,
    action: str,  # "add" | "remove"
    ctx: Any,
) -> None:
    """Cascade a student add/remove to all TAs linked to *teacher_id*."""
    _tpath = str(ctx.resolve_user_profile_path(teacher_id, "education"))
    try:
        _tprofile = await ctx.run_in_threadpool(
            ctx.persistence.load_subject_profile, _tpath,
        )
    except Exception:
        return
    ta_ids = list((_tprofile.get("educator_state") or {}).get("assigned_ta_ids") or [])
    for ta_id in ta_ids:
        _ta_path = str(ctx.resolve_user_profile_path(ta_id, "education"))
        try:
            _ta_prof = await ctx.run_in_threadpool(
                ctx.persistence.load_subject_profile, _ta_path,
            )
        except Exception:
            continue
        _ast = _ta_prof.setdefault("assistant_state", {})
        _ta_students = list(_ast.get("assigned_students") or [])
        if action == "add" and student_id not in _ta_students:
            _ta_students.append(student_id)
        elif action == "remove" and student_id in _ta_students:
            _ta_students.remove(student_id)
        else:
            continue
        _ast["assigned_students"] = _ta_students
        await ctx.run_in_threadpool(
            ctx.persistence.save_subject_profile, _ta_path, _ta_prof,
        )


# ─────────────────────────────────────────────────────────────
# Handler dispatch entry point
# ─────────────────────────────────────────────────────────────

async def handle_operation(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any] | None:
    """Route an education-domain admin operation.

    Returns a result dict if the operation is handled, or ``None``
    if *operation* is not an education operation (so the system
    dispatcher can continue with its own elif chain).
    """
    if operation == "request_module_assignment":
        return await _request_module_assignment(operation, params, user_data, ctx)
    if operation == "assign_student":
        return await _assign_student(operation, params, user_data, ctx)
    if operation == "remove_student":
        return await _remove_student(operation, params, user_data, ctx)
    if operation == "request_teacher_assignment":
        return await _request_teacher_assignment(operation, params, user_data, ctx)
    if operation == "request_ta_assignment":
        return await _request_ta_assignment(operation, params, user_data, ctx)
    if operation == "assign_module":
        return await _assign_module(operation, params, user_data, ctx)
    if operation == "remove_module":
        return await _remove_module(operation, params, user_data, ctx)
    return None


# ─────────────────────────────────────────────────────────────
# Individual operation handlers
# ─────────────────────────────────────────────────────────────

async def _request_module_assignment(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    domain_id = str(params.get("domain_id", ""))
    module_id = str(params.get("module_id", ""))
    reason = str(params.get("reason", "")) or "User requested module assignment"

    if not domain_id:
        raise ctx.HTTPException(status_code=422, detail="domain_id is required")
    if not module_id:
        raise ctx.HTTPException(status_code=422, detail="module_id is required")

    try:
        resolved_domain = ctx.domain_registry.resolve_domain_id(domain_id)
    except Exception as exc:
        raise ctx.HTTPException(status_code=400, detail=str(exc))

    _mods = ctx.domain_registry.list_modules_for_domain(resolved_domain)
    _valid_mod_ids = {m["module_id"] for m in _mods}
    if module_id not in _valid_mod_ids:
        raise ctx.HTTPException(
            status_code=422,
            detail=f"Unknown module_id: {module_id}. Valid modules: {sorted(_valid_mod_ids)}",
        )

    import uuid as _uuid_mod
    escalation_id = str(_uuid_mod.uuid4())
    escalation_record = {
        "record_type": "EscalationRecord",
        "escalation_id": escalation_id,
        "session_id": user_data.get("session_id", "admin"),
        "actor_id": user_data["sub"],
        "domain_id": resolved_domain,
        "module_id": module_id,
        "escalation_type": "module_assignment_request",
        "summary": f"User {user_data.get('username', user_data['sub'])} requests assignment to {module_id}",
        "reason": reason,
        "status": "open",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        ctx.persistence.append_log_record(
            "admin", escalation_record,
            ledger_path=ctx.persistence.get_log_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write module_assignment_request escalation")

    return {
        "operation": operation,
        "escalation_id": escalation_id,
        "domain_id": resolved_domain,
        "module_id": module_id,
        "status": "pending_approval",
        "message": f"Module assignment request submitted. A domain authority for '{resolved_domain}' will review this request.",
    }


async def _assign_student(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    student_id = str(params.get("student_id", "")).strip()
    teacher_id = str(params.get("teacher_id", "")).strip()
    if not student_id:
        raise ctx.HTTPException(status_code=422, detail="student_id required")

    caller_role = user_data["role"]
    if caller_role == "user":
        _has_cap = False
        for _mid, _rid in (user_data.get("domain_roles") or {}).items():
            if _rid in ("teacher",) and ctx.has_domain_capability(user_data, _mid, "receive_escalations"):
                _has_cap = True
                break
        if not _has_cap:
            raise ctx.HTTPException(status_code=403, detail="Requires teacher domain role with receive_escalations capability")
        teacher_id = user_data["sub"]  # force self
    elif caller_role in ("root", "domain_authority"):
        if not teacher_id:
            raise ctx.HTTPException(status_code=422, detail="teacher_id required for domain authorities")
    else:
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    student = await ctx.run_in_threadpool(ctx.persistence.get_user, student_id)
    if student is None:
        raise ctx.HTTPException(status_code=404, detail=f"Student not found: {student_id}")
    teacher = await ctx.run_in_threadpool(ctx.persistence.get_user, teacher_id)
    if teacher is None:
        raise ctx.HTTPException(status_code=404, detail=f"Teacher not found: {teacher_id}")

    if caller_role == "domain_authority":
        _teacher_modules = list((teacher.get("domain_roles") or {}).keys())
        if not any(ctx.can_govern_domain(user_data, m, registry=ctx.domain_registry) for m in _teacher_modules):
            raise ctx.HTTPException(status_code=403, detail="Not authorised — teacher is outside your governed modules")

    _student_profile_path = str(ctx.resolve_user_profile_path(student_id, "education"))
    try:
        _sprofile = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _student_profile_path)
    except Exception:
        _sprofile = {}
    _sprofile["assigned_teacher_id"] = teacher_id
    await ctx.run_in_threadpool(ctx.persistence.save_subject_profile, _student_profile_path, _sprofile)

    _teacher_profile_path = str(ctx.resolve_user_profile_path(teacher_id, "education"))
    try:
        _tprofile = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _teacher_profile_path)
    except Exception:
        _tprofile = {}
    _edu_state = _tprofile.setdefault("educator_state", {})
    _assigned = list(_edu_state.get("assigned_students") or [])
    if student_id not in _assigned:
        _assigned.append(student_id)
    _edu_state["assigned_students"] = _assigned
    await ctx.run_in_threadpool(ctx.persistence.save_subject_profile, _teacher_profile_path, _tprofile)

    await _sync_ta_students(teacher_id, student_id, "add", ctx)

    record = ctx.build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=ctx.map_role_to_actor_role(caller_role),
        commitment_type="student_assignment",
        subject_id=student_id,
        summary=f"Assigned student {student_id} to teacher {teacher_id}",
        metadata={"teacher_id": teacher_id, "assigned_by": user_data["sub"]},
        references=[student_id, teacher_id],
    )
    ctx.persistence.append_log_record(
        "admin", record,
        ledger_path=ctx.persistence.get_log_ledger_path("admin", domain_id="_admin"),
    )
    return {
        "operation": operation,
        "student_id": student_id,
        "teacher_id": teacher_id,
        "status": "assigned",
        "record_id": record["record_id"],
    }


async def _remove_student(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    student_id = str(params.get("student_id", "")).strip()
    teacher_id = str(params.get("teacher_id", "")).strip()
    if not student_id:
        raise ctx.HTTPException(status_code=422, detail="student_id required")

    caller_role = user_data["role"]
    if caller_role == "user":
        _has_cap = False
        for _mid, _rid in (user_data.get("domain_roles") or {}).items():
            if _rid in ("teacher",) and ctx.has_domain_capability(user_data, _mid, "receive_escalations"):
                _has_cap = True
                break
        if not _has_cap:
            raise ctx.HTTPException(status_code=403, detail="Requires teacher domain role with receive_escalations capability")
        teacher_id = user_data["sub"]
    elif caller_role in ("root", "domain_authority"):
        if not teacher_id:
            raise ctx.HTTPException(status_code=422, detail="teacher_id required for domain authorities")
    else:
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    student = await ctx.run_in_threadpool(ctx.persistence.get_user, student_id)
    if student is None:
        raise ctx.HTTPException(status_code=404, detail=f"Student not found: {student_id}")

    _student_profile_path = str(ctx.resolve_user_profile_path(student_id, "education"))
    try:
        _sprofile = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _student_profile_path)
    except Exception:
        _sprofile = {}
    _sprofile.pop("assigned_teacher_id", None)
    await ctx.run_in_threadpool(ctx.persistence.save_subject_profile, _student_profile_path, _sprofile)

    _teacher_profile_path = str(ctx.resolve_user_profile_path(teacher_id, "education"))
    try:
        _tprofile = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _teacher_profile_path)
    except Exception:
        _tprofile = {}
    _edu_state = _tprofile.get("educator_state") or {}
    _assigned = list(_edu_state.get("assigned_students") or [])
    if student_id in _assigned:
        _assigned.remove(student_id)
        _edu_state["assigned_students"] = _assigned
        _tprofile["educator_state"] = _edu_state
        await ctx.run_in_threadpool(ctx.persistence.save_subject_profile, _teacher_profile_path, _tprofile)

    await _sync_ta_students(teacher_id, student_id, "remove", ctx)

    record = ctx.build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=ctx.map_role_to_actor_role(caller_role),
        commitment_type="student_removal",
        subject_id=student_id,
        summary=f"Removed student {student_id} from teacher {teacher_id}",
        metadata={"teacher_id": teacher_id, "removed_by": user_data["sub"]},
        references=[student_id, teacher_id],
    )
    ctx.persistence.append_log_record(
        "admin", record,
        ledger_path=ctx.persistence.get_log_ledger_path("admin", domain_id="_admin"),
    )
    return {
        "operation": operation,
        "student_id": student_id,
        "teacher_id": teacher_id,
        "status": "removed",
        "record_id": record["record_id"],
    }


async def _request_teacher_assignment(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    teacher_id = str(params.get("teacher_id", "")).strip()
    if not teacher_id:
        raise ctx.HTTPException(status_code=422, detail="teacher_id required")

    student_id = user_data["sub"]

    _is_student = any(
        r == "student"
        for r in (user_data.get("domain_roles") or {}).values()
    )
    if not _is_student:
        raise ctx.HTTPException(status_code=403, detail="Only students may request teacher assignment")

    teacher = await ctx.run_in_threadpool(ctx.persistence.get_user, teacher_id)
    if teacher is None:
        raise ctx.HTTPException(status_code=404, detail=f"Teacher not found: {teacher_id}")
    _teacher_roles = list((teacher.get("domain_roles") or {}).values())
    if "teacher" not in _teacher_roles:
        raise ctx.HTTPException(status_code=422, detail=f"{teacher_id} is not a teacher")

    _student_profile_path = str(ctx.resolve_user_profile_path(student_id, "education"))
    try:
        _sprofile = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _student_profile_path)
    except Exception:
        _sprofile = {}
    _sprofile["assigned_teacher_id"] = teacher_id
    await ctx.run_in_threadpool(ctx.persistence.save_subject_profile, _student_profile_path, _sprofile)

    _teacher_profile_path = str(ctx.resolve_user_profile_path(teacher_id, "education"))
    try:
        _tprofile = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _teacher_profile_path)
    except Exception:
        _tprofile = {}
    _edu_state = _tprofile.setdefault("educator_state", {})
    _assigned = list(_edu_state.get("assigned_students") or [])
    if student_id not in _assigned:
        _assigned.append(student_id)
    _edu_state["assigned_students"] = _assigned
    await ctx.run_in_threadpool(ctx.persistence.save_subject_profile, _teacher_profile_path, _tprofile)

    await _sync_ta_students(teacher_id, student_id, "add", ctx)

    record = ctx.build_commitment_record(
        actor_id=student_id,
        actor_role="student",
        commitment_type="student_self_assignment",
        subject_id=student_id,
        summary=f"Student {student_id} self-assigned to teacher {teacher_id}",
        metadata={"teacher_id": teacher_id},
        references=[student_id, teacher_id],
    )
    ctx.persistence.append_log_record(
        "admin", record,
        ledger_path=ctx.persistence.get_log_ledger_path("admin", domain_id="_admin"),
    )
    return {
        "operation": operation,
        "student_id": student_id,
        "teacher_id": teacher_id,
        "status": "assigned",
        "record_id": record["record_id"],
    }


async def _request_ta_assignment(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    teacher_id = str(params.get("teacher_id", "")).strip()
    if not teacher_id:
        raise ctx.HTTPException(status_code=422, detail="teacher_id required")

    ta_id = user_data["sub"]

    _is_ta = any(
        r == "teaching_assistant"
        for r in (user_data.get("domain_roles") or {}).values()
    )
    if not _is_ta:
        raise ctx.HTTPException(status_code=403, detail="Only teaching assistants may request TA assignment")

    teacher = await ctx.run_in_threadpool(ctx.persistence.get_user, teacher_id)
    if teacher is None:
        raise ctx.HTTPException(status_code=404, detail=f"Teacher not found: {teacher_id}")
    _teacher_roles = list((teacher.get("domain_roles") or {}).values())
    if "teacher" not in _teacher_roles:
        raise ctx.HTTPException(status_code=422, detail=f"{teacher_id} is not a teacher")

    _ta_profile_path = str(ctx.resolve_user_profile_path(ta_id, "education"))
    try:
        _ta_prof = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _ta_profile_path)
    except Exception:
        _ta_prof = {}
    _ast = _ta_prof.setdefault("assistant_state", {})
    _ast["supervising_teacher_id"] = teacher_id

    _teacher_profile_path = str(ctx.resolve_user_profile_path(teacher_id, "education"))
    try:
        _tprofile = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _teacher_profile_path)
    except Exception:
        _tprofile = {}
    _edu_state = _tprofile.setdefault("educator_state", {})
    _teacher_students = list(_edu_state.get("assigned_students") or [])
    _ast["assigned_students"] = list(_teacher_students)
    await ctx.run_in_threadpool(ctx.persistence.save_subject_profile, _ta_profile_path, _ta_prof)

    _ta_ids = list(_edu_state.get("assigned_ta_ids") or [])
    if ta_id not in _ta_ids:
        _ta_ids.append(ta_id)
    _edu_state["assigned_ta_ids"] = _ta_ids
    await ctx.run_in_threadpool(ctx.persistence.save_subject_profile, _teacher_profile_path, _tprofile)

    record = ctx.build_commitment_record(
        actor_id=ta_id,
        actor_role="teaching_assistant",
        commitment_type="ta_self_assignment",
        subject_id=ta_id,
        summary=f"TA {ta_id} self-assigned to teacher {teacher_id}",
        metadata={"teacher_id": teacher_id, "inherited_students": _teacher_students},
        references=[ta_id, teacher_id],
    )
    ctx.persistence.append_log_record(
        "admin", record,
        ledger_path=ctx.persistence.get_log_ledger_path("admin", domain_id="_admin"),
    )
    return {
        "operation": operation,
        "ta_id": ta_id,
        "teacher_id": teacher_id,
        "inherited_students": _teacher_students,
        "status": "assigned",
        "record_id": record["record_id"],
    }


async def _assign_module(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    target_user_id = str(params.get("user_id", "") or params.get("_target", "")).strip()
    module_id = str(params.get("module_id", "")).strip()
    if not target_user_id or not module_id:
        raise ctx.HTTPException(status_code=422, detail="user_id and module_id required")

    caller_role = user_data["role"]
    if caller_role in ("root", "domain_authority"):
        if caller_role == "domain_authority" and not ctx.can_govern_domain(user_data, module_id, registry=ctx.domain_registry):
            raise ctx.HTTPException(status_code=403, detail="Not authorised for this domain/module")
    elif caller_role == "user":
        _can_assign = False
        for _mid, _rid in (user_data.get("domain_roles") or {}).items():
            if ctx.has_domain_capability(user_data, _mid, "assign_modules_to_students"):
                _can_assign = True
                break
        if not _can_assign:
            raise ctx.HTTPException(status_code=403, detail="Requires assign_modules_to_students capability")
    else:
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    target = await ctx.run_in_threadpool(ctx.persistence.get_user, target_user_id)
    if target is None:
        raise ctx.HTTPException(status_code=404, detail=f"User not found: {target_user_id}")

    await ctx.run_in_threadpool(
        ctx.persistence.update_user_governed_modules, target_user_id, add=[module_id],
    )
    record = ctx.build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=ctx.map_role_to_actor_role(caller_role),
        commitment_type="module_assignment",
        subject_id=target_user_id,
        summary=f"Assigned module {module_id} to user {target_user_id}",
        metadata={"module_id": module_id, "assigned_by": user_data["sub"]},
        references=[target_user_id, module_id],
    )
    ctx.persistence.append_log_record(
        "admin", record,
        ledger_path=ctx.persistence.get_log_ledger_path("admin", domain_id="_admin"),
    )
    return {
        "operation": operation,
        "user_id": target_user_id,
        "module_id": module_id,
        "status": "assigned",
        "record_id": record["record_id"],
    }


async def _remove_module(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    target_user_id = str(params.get("user_id", "") or params.get("_target", "")).strip()
    module_id = str(params.get("module_id", "")).strip()
    if not target_user_id or not module_id:
        raise ctx.HTTPException(status_code=422, detail="user_id and module_id required")

    caller_role = user_data["role"]
    if caller_role in ("root", "domain_authority"):
        if caller_role == "domain_authority" and not ctx.can_govern_domain(user_data, module_id, registry=ctx.domain_registry):
            raise ctx.HTTPException(status_code=403, detail="Not authorised for this domain/module")
    elif caller_role == "user":
        _can_assign = False
        for _mid, _rid in (user_data.get("domain_roles") or {}).items():
            if ctx.has_domain_capability(user_data, _mid, "assign_modules_to_students"):
                _can_assign = True
                break
        if not _can_assign:
            raise ctx.HTTPException(status_code=403, detail="Requires assign_modules_to_students capability")
    else:
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    target = await ctx.run_in_threadpool(ctx.persistence.get_user, target_user_id)
    if target is None:
        raise ctx.HTTPException(status_code=404, detail=f"User not found: {target_user_id}")

    await ctx.run_in_threadpool(
        ctx.persistence.update_user_governed_modules, target_user_id, remove=[module_id],
    )
    record = ctx.build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=ctx.map_role_to_actor_role(caller_role),
        commitment_type="module_removal",
        subject_id=target_user_id,
        summary=f"Removed module {module_id} from user {target_user_id}",
        metadata={"module_id": module_id, "removed_by": user_data["sub"]},
        references=[target_user_id, module_id],
    )
    ctx.persistence.append_log_record(
        "admin", record,
        ledger_path=ctx.persistence.get_log_ledger_path("admin", domain_id="_admin"),
    )
    return {
        "operation": operation,
        "user_id": target_user_id,
        "module_id": module_id,
        "status": "removed",
        "record_id": record["record_id"],
    }
