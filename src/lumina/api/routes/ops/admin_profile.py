"""Profile operations: view_my_profile, update_user_preferences."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lumina.api.admin_context import AdminOperationContext
from lumina.api import config as _cfg


async def execute(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: AdminOperationContext,
    *,
    parsed: dict[str, Any] | None = None,
    **kw: Any,
) -> dict[str, Any] | None:
    parsed = parsed or {}

    if operation == "view_my_profile":
        caller_id = user_data["sub"]
        domain_key = str(params.get("domain_id", "")).strip()
        if not domain_key:
            domain_key = ctx.domain_registry.resolve_default_for_user(user_data)
        _profile_path = str(Path("data/profiles") / f"{caller_id}.yaml")
        try:
            _profile = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _profile_path)
        except Exception:
            _profile = {}
        # Also try the hierarchical path
        if not _profile or not isinstance(_profile, dict):
            _hier_path = str(ctx.resolve_user_profile_path(caller_id, domain_key))
            try:
                _profile = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _hier_path)
            except Exception:
                _profile = {}
        if not isinstance(_profile, dict):
            _profile = {}
        _prefs = _profile.get("preferences") or {}
        _modules_state = _profile.get("modules") if isinstance(_profile.get("modules"), dict) else {}
        return {
            "operation": operation,
            "user_id": caller_id,
            "display_name": _profile.get("display_name") or _profile.get("name") or caller_id,
            "role": user_data.get("role", ""),
            "preferences": dict(_prefs),
            "assigned_modules": list(_modules_state.keys()),
            "module_summaries": {
                mk: {"turn_count": int((mv if isinstance(mv, dict) else {}).get("turn_count", 0))}
                for mk, mv in _modules_state.items()
            },
        }

    if operation == "update_user_preferences":
        target_user_id = str(params.get("target_user_id", "") or params.get("student_id", "")).strip()
        updates = params.get("updates") or {}
        note = str(params.get("note", "")).strip()
        caller_role = user_data["role"]
        caller_id = user_data["sub"]

        # Self-update is always allowed; cross-user requires elevated system role
        if not target_user_id or target_user_id == caller_id:
            target_user_id = caller_id
        else:
            _ELEVATED_ROLES = ("root", "domain_authority", "it_support")
            if caller_role not in _ELEVATED_ROLES:
                raise ctx.HTTPException(status_code=403, detail="Elevated system role required to update another user's preferences")

        if not isinstance(updates, dict) or not updates:
            raise ctx.HTTPException(status_code=422, detail="updates parameter must be a non-empty object")

        # Load profile
        _profile_path = str(Path("data/profiles") / f"{target_user_id}.yaml")
        try:
            _profile = await ctx.run_in_threadpool(ctx.persistence.load_subject_profile, _profile_path)
        except Exception:
            _profile = {}
        if not isinstance(_profile, dict):
            _profile = {}

        _prefs = _profile.setdefault("preferences", {})
        for k, v in updates.items():
            _prefs[k] = v

        # Audit trail — supervisor note when updating another user
        if note and target_user_id != caller_id:
            _snotes = list(_profile.get("supervisor_notes") or [])
            _snotes.append({
                "author_id": caller_id,
                "note": note,
                "recorded_utc": datetime.now(timezone.utc).isoformat(),
                "context": "preference_update",
            })
            _profile["supervisor_notes"] = _snotes

        await ctx.run_in_threadpool(ctx.persistence.save_subject_profile, _profile_path, _profile)

        record = ctx.build_commitment_record(
            actor_id=caller_id,
            actor_role=ctx.map_role_to_actor_role(caller_role),
            commitment_type="preference_update",
            subject_id=target_user_id,
            summary=f"Updated preferences for {target_user_id}: {', '.join(updates.keys())}",
            metadata={"updates": updates, "note": note},
            references=[target_user_id],
        )
        ctx.persistence.append_log_record(
            "admin", record,
            ledger_path=ctx.persistence.get_system_ledger_path("admin"),
        )
        return {
            "operation": operation,
            "user_id": target_user_id,
            "updated_fields": list(updates.keys()),
            "status": "updated",
            "record_id": record["record_id"],
        }

    return None
