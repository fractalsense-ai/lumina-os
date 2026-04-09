"""Domain-owned API route handlers for the education domain pack.

These callables are declared in runtime-config.yaml under ``adapters.api_routes``
and dynamically mounted by the core server at startup.  Each handler receives
the FastAPI ``Request`` plus injected dependencies (auth user, persistence)
so it remains free of direct imports into ``lumina.api.*``.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina-api.education")


# ── POST /api/user/{user_id}/vocabulary-metric ──────────────

async def post_vocabulary_metric(
    *,
    user_id: str,
    body: dict[str, Any],
    user_data: dict[str, Any],
    persistence: Any,
    resolve_profile_path: Any,
    **_kw: Any,
) -> dict[str, Any]:
    """Student posts a structured complexity metric (no chat content).

    Writes the metric into the student's profile vocabulary_tracking state.
    """
    from starlette.concurrency import run_in_threadpool

    # Students can only update their own metric
    if user_data["user_id"] != user_id and user_data["role"] not in ("root",):
        return {"__status": 403, "detail": "Cannot update another user's vocabulary metric"}

    profile_path = resolve_profile_path(user_id, "education")
    try:
        profile = await run_in_threadpool(
            persistence.load_subject_profile, str(profile_path),
        )
    except Exception:
        return {"__status": 404, "detail": "Student profile not found"}

    ls = profile.setdefault("learning_state", {})
    vt = ls.setdefault("vocabulary_tracking", {})

    score = body.get("vocabulary_complexity_score", 0.0)
    vt["current_complexity"] = score
    vt["measurement_valid"] = body.get("measurement_valid", True)

    vt["_pending_evidence"] = {
        "vocabulary_complexity_score": score,
        "lexical_diversity": body.get("lexical_diversity", 0.0),
        "avg_word_length": body.get("avg_word_length", 0.0),
        "embedding_spread": body.get("embedding_spread", 0.0),
        "domain_terms_detected": body.get("domain_terms_detected", []),
        "buffer_turns": body.get("buffer_turns", 0),
        "measurement_valid": body.get("measurement_valid", True),
    }

    await run_in_threadpool(
        persistence.save_subject_profile, str(profile_path), profile,
    )

    return {"status": "ok", "score": score}


# ── GET /api/dashboard/education/vocabulary-growth ──────────

async def dashboard_vocabulary_growth(
    *,
    user_data: dict[str, Any],
    persistence: Any,
    profiles_dir: Any,
    **_kw: Any,
) -> dict[str, Any]:
    """Teacher / DA / root aggregate vocabulary growth across students."""
    from starlette.concurrency import run_in_threadpool

    results: list[dict[str, Any]] = []

    if not profiles_dir.exists():
        return {"students": results, "summary": {}}

    for user_dir in profiles_dir.iterdir():
        if not user_dir.is_dir():
            continue
        edu_profile = user_dir / "education.yaml"
        if not edu_profile.exists():
            continue
        try:
            profile = await run_in_threadpool(
                persistence.load_subject_profile, str(edu_profile),
            )
        except Exception:
            continue

        ls = profile.get("learning_state") or {}
        vt = ls.get("vocabulary_tracking") or {}
        if not vt.get("current_complexity"):
            continue

        results.append({
            "user_id": user_dir.name,
            "baseline_complexity": vt.get("baseline_complexity"),
            "current_complexity": vt.get("current_complexity"),
            "growth_delta": vt.get("growth_delta", 0.0),
            "last_measured_utc": vt.get("last_measured_utc"),
            "session_count": len(vt.get("session_history") or []),
        })

    deltas = [r["growth_delta"] for r in results if r["growth_delta"] is not None]
    summary = {
        "total_students_tracked": len(results),
        "avg_growth_delta": sum(deltas) / len(deltas) if deltas else 0.0,
        "max_growth_delta": max(deltas) if deltas else 0.0,
    }

    return {"students": results, "summary": summary}
