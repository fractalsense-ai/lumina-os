"""Dashboard roster-status handler for the education domain pack.

Provides colour-coded status indicators for:
- Teachers: see assigned students with risk scores and module info.
- DAs: see teachers with load, queue depth, and resolution stats.

Declared in runtime-config.yaml under ``adapters.api_routes`` and
mounted dynamically by the core server.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina-api.education")

# ── Risk score thresholds ─────────────────────────────────────

_COLOR_THRESHOLDS = (
    (0.25, "green"),
    (0.50, "yellow"),
    (0.75, "orange"),
    (1.01, "red"),
)


def _risk_color(score: float) -> str:
    for threshold, color in _COLOR_THRESHOLDS:
        if score < threshold:
            return color
    return "red"


def _compute_student_risk(module_state: dict[str, Any] | None) -> dict[str, Any]:
    """Compute a 0-1 risk score from a student's module state."""
    if not module_state:
        return {"risk_score": 0.0, "color": "green", "factors": {}}

    rw = module_state.get("recent_window") or {}
    affect = module_state.get("affect") or {}

    consecutive_incorrect = min(rw.get("consecutive_incorrect", 0), 3)
    hint_count = min(rw.get("hint_count", 0), 3)
    outside_pct = min(rw.get("outside_pct", 0.0), 1.0)
    frustration_flag = 1.0 if affect.get("frustration") else 0.0
    valence = affect.get("valence", 0.5)
    valence_factor = max(0.0, min(0.5 - valence, 1.0))

    score = (
        0.30 * (consecutive_incorrect / 3.0)
        + 0.20 * (hint_count / 3.0)
        + 0.20 * outside_pct
        + 0.15 * frustration_flag
        + 0.15 * valence_factor
    )
    score = max(0.0, min(score, 1.0))

    return {
        "risk_score": round(score, 3),
        "color": _risk_color(score),
        "factors": {
            "consecutive_incorrect": rw.get("consecutive_incorrect", 0),
            "hint_count": rw.get("hint_count", 0),
            "outside_pct": round(outside_pct, 3),
            "frustration": bool(frustration_flag),
            "valence": round(valence, 3),
        },
    }


# ── Teacher-level status for DA view ─────────────────────────

_TEACHER_COLOR_THRESHOLDS = {
    # (student_count, pending_count, avg_resolution_min) → color
    # Evaluated in order; first match wins.
}


def _teacher_status_color(
    student_count: int,
    pending_count: int,
    has_sla_breach: bool,
) -> str:
    if pending_count >= 5 or has_sla_breach:
        return "red"
    if student_count > 10 or pending_count >= 3:
        return "orange"
    if student_count >= 5 or pending_count >= 1:
        return "yellow"
    return "green"


# ── Handler: roster_status ────────────────────────────────────

async def roster_status(
    *,
    user_data: dict[str, Any],
    persistence: Any,
    domain_registry: Any = None,
    query_params: dict[str, Any] | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Return roster status with risk indicators, scoped by caller role.

    Teachers see their assigned students.
    DAs see teachers within their governed modules.
    Root sees everything.
    """
    from starlette.concurrency import run_in_threadpool

    caller_role = user_data["role"]
    domain_roles = user_data.get("domain_roles") or {}

    is_teacher = any(rid == "teacher" for rid in domain_roles.values())
    is_da = caller_role == "admin"
    is_root = caller_role == "root"

    if not (is_teacher or is_da or is_root):
        return {"__status": 403, "detail": "Requires teacher, DA, or root role"}

    # ── Teacher view: assigned students with risk scores ──────
    if is_teacher and not (is_da or is_root):
        return await _teacher_view(user_data, persistence, domain_registry)

    # ── DA / root view: teachers with load stats ──────────────
    return await _da_view(user_data, persistence, domain_registry)


async def _teacher_view(
    user_data: dict[str, Any],
    persistence: Any,
    domain_registry: Any,
) -> dict[str, Any]:
    from starlette.concurrency import run_in_threadpool

    teacher_id = user_data["sub"]

    # Load teacher profile to get assigned students
    profiles_dir = _get_profiles_dir()
    teacher_profile = await _load_edu_profile(persistence, profiles_dir, teacher_id)
    edu_state = teacher_profile.get("educator_state") or {}
    assigned_students = list(edu_state.get("assigned_students") or [])

    students: list[dict[str, Any]] = []
    for sid in assigned_students:
        student_profile = await _load_edu_profile(persistence, profiles_dir, sid)
        if not student_profile:
            continue

        # Resolve username
        user_rec = await run_in_threadpool(persistence.get_user, sid)
        username = (user_rec or {}).get("username", sid)

        # Get active module
        active_module = student_profile.get("domain_id") or student_profile.get("subject_domain_id") or ""

        # Load module state for risk computation
        module_state = None
        if active_module:
            module_state = await run_in_threadpool(
                persistence.load_module_state, sid, active_module,
            )

        risk = _compute_student_risk(module_state)

        students.append({
            "student_id": sid,
            "username": username,
            "active_module": active_module,
            "risk_score": risk["risk_score"],
            "color": risk["color"],
            "factors": risk["factors"],
            "mastery": (module_state or {}).get("mastery"),
            "fluency_tier": ((module_state or {}).get("fluency") or {}).get("current_tier"),
        })

    # Sort by risk descending so highest-risk students are first.
    students.sort(key=lambda s: s["risk_score"], reverse=True)

    return {"view": "teacher", "teacher_id": teacher_id, "students": students}


async def _da_view(
    user_data: dict[str, Any],
    persistence: Any,
    domain_registry: Any,
) -> dict[str, Any]:
    from starlette.concurrency import run_in_threadpool

    governed = set(user_data.get("governed_modules") or [])
    is_root = user_data["role"] == "root"

    all_users = await run_in_threadpool(persistence.list_users)

    # Filter to teachers (users with a "teacher" domain_role)
    teacher_users = []
    for u in all_users:
        dr = u.get("domain_roles") or {}
        teacher_modules = [m for m, r in dr.items() if r == "teacher"]
        if not teacher_modules:
            continue
        # DA scope: at least one governed module must overlap
        if not is_root and not any(m in governed for m in teacher_modules):
            continue
        teacher_users.append((u, teacher_modules))

    # Pending escalations for stats
    try:
        all_escalations = await run_in_threadpool(
            persistence.query_escalations, status="pending",
        )
    except Exception:
        all_escalations = []

    profiles_dir = _get_profiles_dir()
    teachers: list[dict[str, Any]] = []
    for user_rec, teacher_modules in teacher_users:
        tid = user_rec.get("user_id") or user_rec.get("sub", "")
        username = user_rec.get("username", tid)

        teacher_profile = await _load_edu_profile(persistence, profiles_dir, tid)
        edu_state = teacher_profile.get("educator_state") or {}
        student_count = len(edu_state.get("assigned_students") or [])

        # Count pending escalations targeted at this teacher
        pending = [
            e for e in all_escalations
            if e.get("escalation_target_id") == tid
        ]
        pending_count = len(pending)

        # SLA breach detection
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        has_sla_breach = False
        for esc in pending:
            ts_str = esc.get("timestamp_utc")
            sla = esc.get("sla_minutes", 30)
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if (now - ts).total_seconds() > sla * 60:
                        has_sla_breach = True
                        break
                except (ValueError, TypeError):
                    pass

        color = _teacher_status_color(student_count, pending_count, has_sla_breach)

        teachers.append({
            "teacher_id": tid,
            "username": username,
            "modules": teacher_modules,
            "student_count": student_count,
            "pending_escalations": pending_count,
            "has_sla_breach": has_sla_breach,
            "color": color,
        })

    # Sort by severity descending
    _color_order = {"red": 0, "orange": 1, "yellow": 2, "green": 3}
    teachers.sort(key=lambda t: _color_order.get(t["color"], 3))

    return {"view": "da", "teachers": teachers}


# ── Helpers ───────────────────────────────────────────────────

def _get_profiles_dir():
    from pathlib import Path
    return Path("data/profiles")


async def _load_edu_profile(
    persistence: Any,
    profiles_dir: Any,
    user_id: str,
) -> dict[str, Any]:
    from starlette.concurrency import run_in_threadpool

    profile_path = profiles_dir / user_id / "education.yaml"
    if not profile_path.exists():
        return {}
    try:
        return await run_in_threadpool(
            persistence.load_subject_profile, str(profile_path),
        )
    except Exception:
        return {}
