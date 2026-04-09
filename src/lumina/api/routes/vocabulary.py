"""Vocabulary tracking endpoints.

POST /api/user/{user_id}/vocabulary-metric
    Student posts a structured complexity metric (no chat content).
    Writes the metric into the student's profile -> vocabulary_tracking.

GET /api/dashboard/education/vocabulary-growth
    Teacher / DA / root view of aggregate vocabulary growth across students.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth

log = logging.getLogger("lumina-api")

router = APIRouter()


# ── Request model ───────────────────────────────────────────

class VocabularyMetricPayload(BaseModel):
    vocabulary_complexity_score: float = Field(ge=0.0, le=1.0)
    lexical_diversity: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_word_length: float = Field(default=0.0, ge=0.0)
    embedding_spread: float = Field(default=0.0, ge=0.0)
    domain_terms_detected: list[str] = Field(default_factory=list)
    buffer_turns: int = Field(default=0, ge=0)
    measurement_valid: bool = True


# ── POST: student submits vocabulary metric ─────────────────

@router.post("/api/user/{user_id}/vocabulary-metric")
async def post_vocabulary_metric(
    user_id: str,
    payload: VocabularyMetricPayload,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    # Students can only update their own metric
    if user_data["user_id"] != user_id and user_data["role"] not in ("root",):
        raise HTTPException(status_code=403, detail="Cannot update another user's vocabulary metric")

    # Find the student's education profile
    profile_path = _cfg._resolve_user_profile_path(user_id, "education")
    try:
        profile = await run_in_threadpool(
            _cfg.PERSISTENCE.load_subject_profile, str(profile_path),
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Student profile not found")

    # Load or init vocabulary_tracking in learning_state
    ls = profile.setdefault("learning_state", {})
    vt = ls.setdefault("vocabulary_tracking", {})

    # Write the metric into the profile vocabulary tracking state
    vt["current_complexity"] = payload.vocabulary_complexity_score
    vt["measurement_valid"] = payload.measurement_valid

    # Store evidence for the domain step to pick up on next turn
    vt["_pending_evidence"] = {
        "vocabulary_complexity_score": payload.vocabulary_complexity_score,
        "lexical_diversity": payload.lexical_diversity,
        "avg_word_length": payload.avg_word_length,
        "embedding_spread": payload.embedding_spread,
        "domain_terms_detected": payload.domain_terms_detected,
        "buffer_turns": payload.buffer_turns,
        "measurement_valid": payload.measurement_valid,
    }

    await run_in_threadpool(
        _cfg.PERSISTENCE.save_subject_profile, str(profile_path), profile,
    )

    return {"status": "ok", "score": payload.vocabulary_complexity_score}


# ── GET: teacher/DA dashboard aggregate ─────────────────────

@router.get("/api/dashboard/education/vocabulary-growth")
async def dashboard_vocabulary_growth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority", "teacher"):
        raise HTTPException(status_code=403, detail="Requires teacher, DA, or root role")

    # Scan all education profiles for vocabulary tracking data
    profiles_dir = _cfg._PROFILES_DIR
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
                _cfg.PERSISTENCE.load_subject_profile, str(edu_profile),
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

    # Summary statistics
    deltas = [r["growth_delta"] for r in results if r["growth_delta"] is not None]
    summary = {
        "total_students_tracked": len(results),
        "avg_growth_delta": sum(deltas) / len(deltas) if deltas else 0.0,
        "max_growth_delta": max(deltas) if deltas else 0.0,
    }

    return {"students": results, "summary": summary}
