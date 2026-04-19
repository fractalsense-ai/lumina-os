"""Roster operations: assign_student, remove_student, assign_ta, assign_guardian.

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

    # Update teacher profile — add student and grant teacher domain_roles
    # for the student's active module so escalations are routable.
    _tprofile = await load_profile(ctx, teacher_id)
    _edu_state = _tprofile.setdefault("educator_state", {})
    _assigned = list(_edu_state.get("assigned_students") or [])
    if student_id not in _assigned:
        _assigned.append(student_id)
    _edu_state["assigned_students"] = _assigned

    _student_domain_id = _sprofile.get("domain_id") or _sprofile.get("subject_domain_id")
    if _student_domain_id:
        _t_domain_roles = _tprofile.setdefault("domain_roles", {})
        if _student_domain_id not in _t_domain_roles:
            _t_domain_roles[_student_domain_id] = "teacher"

    await save_profile(ctx, teacher_id, _tprofile)

    # Sync domain_roles to the user record so JWT includes them.
    if _student_domain_id:
        await ctx.run_in_threadpool(
            ctx.persistence.update_user_domain_roles,
            teacher_id,
            {_student_domain_id: "teacher"},
        )

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


# ── assign_ta ─────────────────────────────────────────────────

async def assign_ta(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Assign a teaching assistant to one or more students.

    Teachers can only assign TAs linked to themselves; domain authorities
    can assign any TA.  If the TA has a supervising teacher the students
    are also placed on that teacher's roster.
    """
    ta_id = str(params.get("ta_id", "")).strip()
    raw_students = str(params.get("student_ids", "")).strip()
    if not ta_id:
        raise ctx.HTTPException(status_code=422, detail="ta_id required")
    if not raw_students:
        raise ctx.HTTPException(status_code=422, detail="student_ids required")

    student_ids_raw = [s.strip() for s in raw_students.split(",") if s.strip()]

    caller_role = user_data["role"]
    if caller_role == "user":
        await require_teacher_capability(user_data, ctx)
    elif caller_role not in ("root", "domain_authority"):
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    ta_rec = await require_user_exists(ctx, ta_id, "Teaching assistant")
    ta_id = ta_rec["user_id"]

    ta_profile = await load_profile(ctx, ta_id)
    _ast = ta_profile.setdefault("assistant_state", {})
    supervising_teacher_id = _ast.get("supervising_teacher_id")

    if caller_role == "user":
        if supervising_teacher_id and supervising_teacher_id != user_data["sub"]:
            raise ctx.HTTPException(
                status_code=403,
                detail="TA is not linked to your roster",
            )

    if not supervising_teacher_id:
        log.warning("assign_ta: TA %s has no supervising teacher — proceeding with warning", ta_id)

    assigned: list[str] = []
    for sid_raw in student_ids_raw:
        s_rec = await require_user_exists(ctx, sid_raw, "Student")
        sid = s_rec["user_id"]

        ta_students = list(_ast.get("assigned_students") or [])
        if sid not in ta_students:
            ta_students.append(sid)
            _ast["assigned_students"] = ta_students

        if supervising_teacher_id:
            t_profile = await load_profile(ctx, supervising_teacher_id)
            t_edu = t_profile.setdefault("educator_state", {})
            t_students = list(t_edu.get("assigned_students") or [])
            if sid not in t_students:
                t_students.append(sid)
                t_edu["assigned_students"] = t_students
                await save_profile(ctx, supervising_teacher_id, t_profile)

            s_profile = await load_profile(ctx, sid)
            s_profile["assigned_teacher_id"] = supervising_teacher_id
            await save_profile(ctx, sid, s_profile)

            # Sync teacher domain_roles to user DB for JWT (same as assign_student).
            _s_domain = s_profile.get("domain_id") or s_profile.get("subject_domain_id")
            if _s_domain:
                _t_dr = t_profile.setdefault("domain_roles", {})
                if _s_domain not in _t_dr:
                    _t_dr[_s_domain] = "teacher"
                    await save_profile(ctx, supervising_teacher_id, t_profile)
                await ctx.run_in_threadpool(
                    ctx.persistence.update_user_domain_roles,
                    supervising_teacher_id,
                    {_s_domain: "teacher"},
                )

        assigned.append(sid)

    await save_profile(ctx, ta_id, ta_profile)

    record = write_commitment(
        ctx,
        actor_id=user_data["sub"],
        actor_role=ctx.map_role_to_actor_role(caller_role),
        commitment_type="ta_student_assignment",
        subject_id=ta_id,
        summary=f"Assigned TA {ta_id} to students {', '.join(assigned)}",
        metadata={
            "ta_id": ta_id,
            "student_ids": assigned,
            "supervising_teacher_id": supervising_teacher_id,
            "assigned_by": user_data["sub"],
        },
        references=[ta_id, *assigned],
    )
    return {
        "operation": operation,
        "ta_id": ta_id,
        "student_ids": assigned,
        "supervising_teacher_id": supervising_teacher_id,
        "status": "assigned",
        "record_id": record["record_id"],
    }


# ── assign_guardian ───────────────────────────────────────────

async def assign_guardian(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Assign a guardian to a student.

    * Students can self-assign: ``/assign guardian <guardian_id>`` — the
      student_id is inferred from the caller.
    * Teachers and domain authorities must provide both IDs.
    * Supports multiple guardians per student (list-based).
    """
    guardian_id = str(params.get("guardian_id", "")).strip()
    student_id = str(params.get("student_id", "")).strip()
    if not guardian_id:
        raise ctx.HTTPException(status_code=422, detail="guardian_id required")

    caller_role = user_data["role"]
    caller_domain_roles = (user_data.get("domain_roles") or {})
    caller_education_role = caller_domain_roles.get("education")

    if caller_education_role == "student" or (caller_role == "user" and not caller_education_role):
        student_id = user_data["sub"]
    elif caller_role == "user":
        await require_teacher_capability(user_data, ctx)
        if not student_id:
            raise ctx.HTTPException(status_code=422, detail="student_id required for teacher callers")
    elif caller_role in ("root", "domain_authority"):
        if not student_id:
            raise ctx.HTTPException(status_code=422, detail="student_id required for domain authorities")
    else:
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    g_rec = await require_user_exists(ctx, guardian_id, "Guardian")
    guardian_id = g_rec["user_id"]

    s_rec = await require_user_exists(ctx, student_id, "Student")
    student_id = s_rec["user_id"]

    # Update student profile — assigned_guardians list
    s_profile = await load_profile(ctx, student_id)
    guardians = list(s_profile.get("assigned_guardians") or [])
    if guardian_id not in guardians:
        guardians.append(guardian_id)
    s_profile["assigned_guardians"] = guardians
    await save_profile(ctx, student_id, s_profile)

    # Update guardian profile — guardian_state.assigned_children list
    g_profile = await load_profile(ctx, guardian_id)
    g_state = g_profile.setdefault("guardian_state", {})
    children = list(g_state.get("assigned_children") or [])
    if student_id not in children:
        children.append(student_id)
    g_state["assigned_children"] = children
    await save_profile(ctx, guardian_id, g_profile)

    record = write_commitment(
        ctx,
        actor_id=user_data["sub"],
        actor_role=ctx.map_role_to_actor_role(caller_role),
        commitment_type="guardian_assignment",
        subject_id=student_id,
        summary=f"Assigned guardian {guardian_id} to student {student_id}",
        metadata={
            "guardian_id": guardian_id,
            "student_id": student_id,
            "assigned_by": user_data["sub"],
        },
        references=[guardian_id, student_id],
    )
    return {
        "operation": operation,
        "guardian_id": guardian_id,
        "student_id": student_id,
        "status": "assigned",
        "record_id": record["record_id"],
    }
