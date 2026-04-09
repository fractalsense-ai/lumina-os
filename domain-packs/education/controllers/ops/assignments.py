"""Assignment-request operations: request_teacher_assignment,
request_ta_assignment, request_module_assignment.

These are self-service flows initiated by students or TAs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ._helpers import (
    load_profile,
    require_user_exists,
    save_profile,
    write_commitment,
)

log = logging.getLogger("lumina.education-ops")


# ── request_module_assignment ─────────────────────────────────

async def request_module_assignment(
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


# ── request_teacher_assignment ────────────────────────────────

async def request_teacher_assignment(
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

    teacher = await require_user_exists(ctx, teacher_id, "Teacher")
    _teacher_roles = list((teacher.get("domain_roles") or {}).values())
    if "teacher" not in _teacher_roles:
        raise ctx.HTTPException(status_code=422, detail=f"{teacher_id} is not a teacher")

    # Update student profile
    _sprofile = await load_profile(ctx, student_id)
    _sprofile["assigned_teacher_id"] = teacher_id
    await save_profile(ctx, student_id, _sprofile)

    # Update teacher profile
    _tprofile = await load_profile(ctx, teacher_id)
    _edu_state = _tprofile.setdefault("educator_state", {})
    _assigned = list(_edu_state.get("assigned_students") or [])
    if student_id not in _assigned:
        _assigned.append(student_id)
    _edu_state["assigned_students"] = _assigned
    await save_profile(ctx, teacher_id, _tprofile)

    # Cascade to TAs
    from .roster import _sync_ta_students
    await _sync_ta_students(teacher_id, student_id, "add", ctx)

    record = write_commitment(
        ctx,
        actor_id=student_id,
        actor_role="student",
        commitment_type="student_self_assignment",
        subject_id=student_id,
        summary=f"Student {student_id} self-assigned to teacher {teacher_id}",
        metadata={"teacher_id": teacher_id},
        references=[student_id, teacher_id],
    )
    return {
        "operation": operation,
        "student_id": student_id,
        "teacher_id": teacher_id,
        "status": "assigned",
        "record_id": record["record_id"],
    }


# ── request_ta_assignment ─────────────────────────────────────

async def request_ta_assignment(
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

    teacher = await require_user_exists(ctx, teacher_id, "Teacher")
    _teacher_roles = list((teacher.get("domain_roles") or {}).values())
    if "teacher" not in _teacher_roles:
        raise ctx.HTTPException(status_code=422, detail=f"{teacher_id} is not a teacher")

    # Update TA profile
    _ta_prof = await load_profile(ctx, ta_id)
    _ast = _ta_prof.setdefault("assistant_state", {})
    _ast["supervising_teacher_id"] = teacher_id

    # Load teacher profile and inherit students
    _tprofile = await load_profile(ctx, teacher_id)
    _edu_state = _tprofile.setdefault("educator_state", {})
    _teacher_students = list(_edu_state.get("assigned_students") or [])
    _ast["assigned_students"] = list(_teacher_students)
    await save_profile(ctx, ta_id, _ta_prof)

    # Register TA with teacher
    _ta_ids = list(_edu_state.get("assigned_ta_ids") or [])
    if ta_id not in _ta_ids:
        _ta_ids.append(ta_id)
    _edu_state["assigned_ta_ids"] = _ta_ids
    await save_profile(ctx, teacher_id, _tprofile)

    record = write_commitment(
        ctx,
        actor_id=ta_id,
        actor_role="teaching_assistant",
        commitment_type="ta_self_assignment",
        subject_id=ta_id,
        summary=f"TA {ta_id} self-assigned to teacher {teacher_id}",
        metadata={"teacher_id": teacher_id, "inherited_students": _teacher_students},
        references=[ta_id, teacher_id],
    )
    return {
        "operation": operation,
        "ta_id": ta_id,
        "teacher_id": teacher_id,
        "inherited_students": _teacher_students,
        "status": "assigned",
        "record_id": record["record_id"],
    }
