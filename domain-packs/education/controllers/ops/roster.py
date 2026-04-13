"""Roster operations: assign_student, remove_student.

Also contains the TA ↔ teacher student-roster sync helper used
when students are added/removed from a teacher's roster.
"""

from __future__ import annotations

from typing import Any

from ._helpers import (
    load_profile,
    log,
    require_teacher_capability,
    require_user_exists,
    save_profile,
    write_commitment,
)


# ── TA cascade sync ──────────────────────────────────────────

async def _sync_ta_students(
    teacher_id: str,
    student_id: str,
    action: str,  # "add" | "remove"
    ctx: Any,
) -> None:
    """Cascade a student add/remove to all TAs linked to *teacher_id*."""
    _tprofile = await load_profile(ctx, teacher_id)
    ta_ids = list((_tprofile.get("educator_state") or {}).get("assigned_ta_ids") or [])
    for ta_id in ta_ids:
        _ta_prof = await load_profile(ctx, ta_id)
        _ast = _ta_prof.setdefault("assistant_state", {})
        _ta_students = list(_ast.get("assigned_students") or [])
        if action == "add" and student_id not in _ta_students:
            _ta_students.append(student_id)
        elif action == "remove" and student_id in _ta_students:
            _ta_students.remove(student_id)
        else:
            continue
        _ast["assigned_students"] = _ta_students
        await save_profile(ctx, ta_id, _ta_prof)


# ── assign_student ────────────────────────────────────────────

async def assign_student(
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
        await require_teacher_capability(user_data, ctx)
        teacher_id = user_data["sub"]  # force self
    elif caller_role in ("root", "domain_authority"):
        if not teacher_id:
            raise ctx.HTTPException(status_code=422, detail="teacher_id required for domain authorities")
    else:
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    student_rec = await require_user_exists(ctx, student_id, "Student")
    student_id = student_rec["user_id"]  # normalise — input may be a username
    teacher = await require_user_exists(ctx, teacher_id, "Teacher")
    teacher_id = teacher["user_id"]  # normalise

    if caller_role == "domain_authority":
        _teacher_modules = list((teacher.get("domain_roles") or {}).keys())
        if not any(ctx.can_govern_domain(user_data, m, registry=ctx.domain_registry) for m in _teacher_modules):
            raise ctx.HTTPException(status_code=403, detail="Not authorised — teacher is outside your governed modules")

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

    await _sync_ta_students(teacher_id, student_id, "add", ctx)

    record = write_commitment(
        ctx,
        actor_id=user_data["sub"],
        actor_role=ctx.map_role_to_actor_role(caller_role),
        commitment_type="student_assignment",
        subject_id=student_id,
        summary=f"Assigned student {student_id} to teacher {teacher_id}",
        metadata={"teacher_id": teacher_id, "assigned_by": user_data["sub"]},
        references=[student_id, teacher_id],
    )
    return {
        "operation": operation,
        "student_id": student_id,
        "teacher_id": teacher_id,
        "status": "assigned",
        "record_id": record["record_id"],
    }


# ── remove_student ────────────────────────────────────────────

async def remove_student(
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
        await require_teacher_capability(user_data, ctx)
        teacher_id = user_data["sub"]
    elif caller_role in ("root", "domain_authority"):
        if not teacher_id:
            raise ctx.HTTPException(status_code=422, detail="teacher_id required for domain authorities")
    else:
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    student_rec = await require_user_exists(ctx, student_id, "Student")
    student_id = student_rec["user_id"]  # normalise — input may be a username

    # Update student profile
    _sprofile = await load_profile(ctx, student_id)
    _sprofile.pop("assigned_teacher_id", None)
    await save_profile(ctx, student_id, _sprofile)

    # Update teacher profile
    _tprofile = await load_profile(ctx, teacher_id)
    _edu_state = _tprofile.get("educator_state") or {}
    _assigned = list(_edu_state.get("assigned_students") or [])
    if student_id in _assigned:
        _assigned.remove(student_id)
        _edu_state["assigned_students"] = _assigned
        _tprofile["educator_state"] = _edu_state
        await save_profile(ctx, teacher_id, _tprofile)

    await _sync_ta_students(teacher_id, student_id, "remove", ctx)

    record = write_commitment(
        ctx,
        actor_id=user_data["sub"],
        actor_role=ctx.map_role_to_actor_role(caller_role),
        commitment_type="student_removal",
        subject_id=student_id,
        summary=f"Removed student {student_id} from teacher {teacher_id}",
        metadata={"teacher_id": teacher_id, "removed_by": user_data["sub"]},
        references=[student_id, teacher_id],
    )
    return {
        "operation": operation,
        "student_id": student_id,
        "teacher_id": teacher_id,
        "status": "removed",
        "record_id": record["record_id"],
    }
