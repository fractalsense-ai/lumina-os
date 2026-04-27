"""Domain-owned escalation REST handlers for the education domain pack.

These callables are declared in runtime-config.yaml under ``adapters.api_routes``
and dynamically mounted by the core server at startup.  Each handler receives
auth-verified ``user_data`` plus injected dependencies so it remains free of
direct imports into ``lumina.api.middleware``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("lumina-api.education")

# ── Trigger type → human-readable label map ───────────────────

_TRIGGER_LABELS: dict[str, str] = {
    "zpd_drift_major": "ZPD drift — student is consistently outside their zone of proximal development",
    "standing_order_exhausted": "Standing order exhausted — automated interventions depleted",
    "critical_invariant_violation": "Critical invariant violation — safety or integrity boundary crossed",
    "frustration_detected": "Frustration detected — multiple frustration markers observed",
    "content_safety": "Content safety — potentially unsafe content flagged",
    "consecutive_incorrect": "Consecutive incorrect — repeated wrong answers without progress",
    "manual_escalation": "Manual escalation — student or system requested teacher intervention",    "wellness_critical": "Wellness critical \u2014 sustained cross-session wellness signals require trusted adult review",}


# ── Capability helpers (domain-specific) ──────────────────────


def _has_escalation_capability(
    user_data: dict[str, Any],
    module_id: str,
    domain_registry: Any,
) -> bool:
    """Check if user has a domain role with ``receive_escalations: true`` for *module_id*."""
    domain_roles_map = user_data.get("domain_roles") or {}
    role_id = domain_roles_map.get(module_id)
    if not role_id:
        return False
    if domain_registry is None:
        return False
    try:
        for domain_info in domain_registry.list_domains():
            modules = domain_registry.list_modules_for_domain(domain_info["domain_id"])
            for mod in modules:
                if mod["module_id"] != module_id:
                    continue
                physics_path = mod.get("domain_physics_path")
                if not physics_path or not Path(physics_path).is_file():
                    return False
                with open(physics_path, encoding="utf-8") as fh:
                    physics = json.load(fh)
                for r in (physics.get("domain_roles") or {}).get("roles", []):
                    if r.get("role_id") == role_id:
                        return bool(
                            (r.get("scoped_capabilities") or {}).get("receive_escalations")
                        )
                return False
    except Exception:
        log.debug("Could not check escalation capability for %s", module_id, exc_info=True)
    return False


# ── Handler: list_escalations ─────────────────────────────────


async def list_escalations(
    *,
    user_data: dict[str, Any],
    persistence: Any,
    domain_registry: Any = None,
    query_params: dict[str, Any] | None = None,
    **_kw: Any,
) -> list[dict[str, Any]] | dict[str, Any]:
    """List escalation records, scoped by caller's role and capabilities."""
    from starlette.concurrency import run_in_threadpool

    qp = query_params or {}
    status = qp.get("status") or None
    domain_id = qp.get("domain_id") or None
    limit = int(qp.get("limit", 100))
    offset = int(qp.get("offset", 0))

    allowed_roles = ("root", "super_admin", "operator", "half_operator")
    is_admin = user_data["role"] == "admin"

    has_esc_capability = False
    if user_data["role"] not in allowed_roles and not is_admin:
        domain_roles_map = user_data.get("domain_roles") or {}
        for mod_id in domain_roles_map:
            if _has_escalation_capability(user_data, mod_id, domain_registry):
                has_esc_capability = True
                break
        if not has_esc_capability:
            return {"__status": 403, "detail": "Insufficient permissions"}

    records = await run_in_threadpool(
        persistence.query_escalations,
        status=status,
        domain_id=domain_id if not (is_admin or has_esc_capability) else None,
        limit=limit,
        offset=offset,
    )

    if is_admin:
        governed = user_data.get("governed_modules") or []
        records = [r for r in records if r.get("domain_pack_id") in governed]
    elif has_esc_capability:
        allowed_modules = {
            mod_id for mod_id in (user_data.get("domain_roles") or {})
            if _has_escalation_capability(user_data, mod_id, domain_registry)
        }
        records = [r for r in records if r.get("domain_pack_id") in allowed_modules]
        # Teacher scoping: only show escalations targeted at this teacher
        # or unassigned (target_id is None/empty).
        caller_id = user_data["sub"]
        records = [
            r for r in records
            if not r.get("escalation_target_id") or r["escalation_target_id"] == caller_id
        ]

    # ── Enrich records with human-readable context ────────────
    records = await _enrich_escalation_records(records, persistence)

    return records


async def _enrich_escalation_records(
    records: list[dict[str, Any]],
    persistence: Any,
) -> list[dict[str, Any]]:
    """Add reason, evidence subset, and student username to escalation records."""
    from starlette.concurrency import run_in_threadpool

    # Resolve actor_id → username in batch
    actor_ids = {r.get("actor_id") for r in records if r.get("actor_id")}
    username_map: dict[str, str] = {}
    for aid in actor_ids:
        try:
            user_rec = await run_in_threadpool(persistence.get_user, aid)
            if user_rec:
                username_map[aid] = user_rec.get("username", aid)
        except Exception:
            pass

    enriched = []
    for r in records:
        # Human-readable reason
        trigger_type = r.get("trigger", "")
        reason = _TRIGGER_LABELS.get(trigger_type, trigger_type)

        # Evidence subset from domain_lib_decision
        dld = r.get("domain_lib_decision") or {}
        evidence = {
            "frustration": bool(dld.get("domain_alert_flag")),
            "drift_pct": dld.get("domain_metric_pct"),
            "tier": dld.get("tier"),
        }

        # Student username
        actor_id = r.get("actor_id", "")
        student_username = username_map.get(actor_id, actor_id)

        # Merge into a copy of the record
        enriched_rec = dict(r)
        enriched_rec["reason"] = reason
        enriched_rec["evidence"] = evidence
        enriched_rec["student_username"] = student_username
        enriched_rec["active_module"] = r.get("domain_pack_id", "")
        enriched.append(enriched_rec)

    return enriched


# ── Handler: get_escalation_detail ────────────────────────────


async def get_escalation_detail(
    *,
    user_data: dict[str, Any],
    persistence: Any,
    domain_registry: Any = None,
    path_params: dict[str, str] | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Return a single escalation record by ID."""
    from lumina.system_log.admin_operations import can_govern_domain
    from starlette.concurrency import run_in_threadpool

    escalation_id = (path_params or {}).get("escalation_id", "")

    allowed_roles = ("root", "super_admin", "operator", "half_operator", "admin")
    quick_pass = user_data["role"] in allowed_roles

    if not quick_pass:
        domain_roles_map = user_data.get("domain_roles") or {}
        if not any(_has_escalation_capability(user_data, m, domain_registry) for m in domain_roles_map):
            return {"__status": 403, "detail": "Insufficient permissions"}

    all_escalations = await run_in_threadpool(persistence.query_escalations)
    target = None
    for esc in all_escalations:
        if esc.get("record_id") == escalation_id:
            target = esc
            break

    if target is None:
        return {"__status": 404, "detail": "Escalation not found"}

    module_id = target.get("domain_pack_id", "")

    if user_data["role"] == "admin":
        if not can_govern_domain(user_data, module_id, registry=domain_registry):
            return {"__status": 403, "detail": "Not authorized for this domain"}
    elif not quick_pass:
        if not _has_escalation_capability(user_data, module_id, domain_registry):
            return {"__status": 403, "detail": "Insufficient permissions"}

    return target


# ── Handler: clear_stale_escalations ──────────────────────────


async def clear_stale_escalations(
    *,
    user_data: dict[str, Any],
    persistence: Any,
    query_params: dict[str, Any] | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Purge escalation records older than *max_age_hours*. Root only."""
    from starlette.concurrency import run_in_threadpool

    if user_data["role"] != "root":
        return {"__status": 403, "detail": "Root only"}

    qp = query_params or {}
    max_age_hours = int(qp.get("max_age_hours", 24))

    all_esc = await run_in_threadpool(
        persistence.query_escalations, limit=10000,
    )
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
    stale_ids: list[str] = []
    for esc in all_esc:
        ts_str = esc.get("timestamp_utc", "")
        try:
            ts = datetime.fromisoformat(ts_str).timestamp()
        except (ValueError, TypeError):
            ts = 0.0
        if ts < cutoff and esc.get("status", "open") == "open":
            stale_ids.append(esc["record_id"])

    for rid in stale_ids:
        expired = {
            "record_type": "EscalationRecord",
            "record_id": rid,
            "status": "expired",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        persistence.append_log_record(
            "admin", expired,
            ledger_path=persistence.get_system_ledger_path("admin"),
        )

    return {"purged": len(stale_ids), "max_age_hours": max_age_hours}


# ── Handler: resolve_escalation ───────────────────────────────


async def resolve_escalation(
    *,
    user_data: dict[str, Any],
    persistence: Any,
    domain_registry: Any = None,
    session_containers: dict[str, Any] | None = None,
    path_params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Resolve an open escalation with a decision (approve/reject/defer)."""
    from lumina.core.session_unlock import generate_unlock_pin, freeze_user
    from lumina.system_log.admin_operations import (
        build_commitment_record,
        can_govern_domain,
        map_role_to_actor_role,
    )
    from starlette.concurrency import run_in_threadpool

    containers = session_containers or {}
    escalation_id = (path_params or {}).get("escalation_id", "")
    b = body or {}

    decision = b.get("decision", "")
    reasoning = b.get("reasoning", "")
    generate_pin = b.get("generate_pin", False)
    intervention_notes = b.get("intervention_notes")
    generate_proposal = b.get("generate_proposal", False)

    if decision not in ("approve", "reject", "defer"):
        return {"__status": 400, "detail": "decision must be approve, reject, or defer"}

    _role = user_data["role"]
    _quick_pass = _role in ("root", "admin")

    all_escalations = await run_in_threadpool(persistence.query_escalations)
    target = None
    for esc in all_escalations:
        if esc.get("record_id") == escalation_id:
            target = esc
            break

    if target is None:
        return {"__status": 404, "detail": "Escalation not found"}

    module_id = target.get("domain_pack_id", "")

    if _role == "admin":
        if not can_govern_domain(user_data, module_id, registry=domain_registry):
            return {"__status": 403, "detail": "Not authorized for this domain"}
    elif not _quick_pass:
        if not _has_escalation_capability(user_data, module_id, domain_registry):
            return {"__status": 403, "detail": "Insufficient permissions"}
        # Teacher scoping: can only resolve escalations targeted at them
        # or unassigned (no escalation_target_id).
        esc_target = target.get("escalation_target_id")
        if esc_target and esc_target != user_data["sub"]:
            return {"__status": 403, "detail": "Not authorized for this escalation"}

    record = build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        commitment_type="escalation_resolution",
        subject_id=escalation_id,
        summary=f"Escalation {decision}: {reasoning[:200]}",
        metadata={
            "decision": decision,
            "reasoning": reasoning,
            "original_trigger": target.get("trigger", ""),
        },
        references=[escalation_id],
    )

    session_id = target.get("session_id", "admin")
    persistence.append_log_record(
        session_id, record,
        ledger_path=persistence.get_system_ledger_path(session_id),
    )

    # ── Mark original EscalationRecord as resolved ──
    resolved_esc = dict(target)
    resolved_esc["status"] = "resolved"
    resolved_esc["resolution_commitment_id"] = record["record_id"]
    persistence.append_log_record(
        session_id, resolved_esc,
        ledger_path=persistence.get_system_ledger_path(session_id),
    )

    # ── PIN generation ── freeze session so student must unlock with OTP ──
    response_extra: dict[str, Any] = {}
    if generate_pin:
        pin = generate_unlock_pin(session_id, escalation_id)
        response_extra["unlock_pin"] = pin
        container = containers.get(session_id)
        if container is not None:
            container.frozen = True
            _freeze_uid = ""
            if hasattr(container, "user") and container.user:
                _freeze_uid = container.user.get("sub", "")
            if _freeze_uid:
                freeze_user(_freeze_uid, escalation_id=escalation_id, session_id=session_id)
        log.info("[%s] Session frozen; unlock PIN issued for escalation %s", session_id, escalation_id)

    # ── Intervention notes ── append to student profile if present ────────
    if intervention_notes:
        actor_id = target.get("actor_id", "")
        if actor_id:
            profile_path: str | None = None
            container = containers.get(session_id)
            if container is not None:
                try:
                    profile_path = container.active_context.subject_profile_path
                except (KeyError, AttributeError):
                    pass
            if profile_path:
                try:
                    profile = await run_in_threadpool(
                        persistence.load_subject_profile, profile_path
                    )
                    if isinstance(profile, dict):
                        history = list(profile.get("intervention_history") or [])
                        history.append({
                            "escalation_id": escalation_id,
                            "teacher_id": user_data["sub"],
                            "notes": intervention_notes,
                            "recorded_utc": datetime.now(timezone.utc).isoformat(),
                            "generated_proposal": bool(generate_proposal),
                        })
                        profile["intervention_history"] = history
                        await run_in_threadpool(
                            persistence.save_subject_profile, profile_path, profile
                        )
                except Exception:
                    log.debug("Could not update student profile with intervention notes", exc_info=True)

    return {
        "record_id": record["record_id"],
        "escalation_id": escalation_id,
        "decision": decision,
        **response_extra,
    }


# ── Handler: wellness_critical_escalation ─────────────────────
# Called by journal_adapters._create_wellness_escalation() — not a
# direct API endpoint.  Resolves routing (Safe Person → teacher fallback)
# and notifies the appropriate adult.


async def route_wellness_escalation(
    *,
    student_id: str,
    escalation_record: dict[str, Any],
    persistence: Any,
    ctx: Any | None = None,
) -> dict[str, Any]:
    """Route a wellness_critical escalation to the Safe Person or teacher.

    Looks up the student profile to find ``assigned_safe_person_id`` and
    ``assigned_teacher_id``.  Routes to the Safe Person when available and
    their handshake is accepted; otherwise falls back to the teacher.

    The escalation record is persisted to the system ledger.  Any PII or
    entity data must have been stripped before calling this function —
    only aggregate evidence (valence, arousal, turn counts) may be present.

    Args:
        student_id:         The student's user ID.
        escalation_record:  An EscalationRecord-compatible dict, already
                            built by the caller with aggregate evidence only.
        persistence:        The persistence adapter.
        ctx:                Optional request context (used for HTTP helpers).

    Returns:
        A dict with {routed_to, target_id, escalation_id}.
    """
    from starlette.concurrency import run_in_threadpool

    profile_path = None
    if ctx is not None:
        try:
            profile_path = str(ctx.resolve_user_profile_path(student_id, "education"))
        except Exception:
            pass

    profile: dict[str, Any] = {}
    if profile_path:
        try:
            profile = await run_in_threadpool(persistence.load_subject_profile, profile_path)
        except Exception:
            pass

    safe_person_id: str | None = profile.get("assigned_safe_person_id")
    handshake_accepted: bool = bool(profile.get("safe_person_handshake_accepted", False))
    teacher_id: str | None = profile.get("assigned_teacher_id")

    if safe_person_id and handshake_accepted:
        target_id = safe_person_id
        routed_to = "safe_person"
    elif teacher_id:
        target_id = teacher_id
        routed_to = "teacher_fallback"
    else:
        target_id = None
        routed_to = "unrouted"
        log.warning(
            "[WELLNESS] No routing target for student=%s; escalation persisted but undelivered",
            student_id,
        )

    rec = dict(escalation_record)
    rec["escalation_target_id"] = target_id
    rec["metadata"] = {
        **(rec.get("metadata") or {}),
        "routed_to": routed_to,
    }

    session_id = rec.get("session_id", "admin")
    persistence.append_log_record(
        session_id, rec,
        ledger_path=persistence.get_system_ledger_path(session_id),
    )

    log.info(
        "[WELLNESS] Escalation %s routed=%s target=%s student=%s",
        rec.get("record_id"), routed_to, target_id, student_id,
    )
    return {
        "routed_to": routed_to,
        "target_id": target_id,
        "escalation_id": rec.get("record_id"),
    }
