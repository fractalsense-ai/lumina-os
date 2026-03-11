"""
admin_operations.py — Shared admin operation logic for API endpoints and CLI tools.

Provides CTL record builders, validation helpers, and common admin
operation infrastructure used by lumina-api-server.py and CLI tools.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any


# ─────────────────────────────────────────────────────────────
# CTL Record Builders
# ─────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_sha256(value: Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_trace_event(
    *,
    session_id: str,
    actor_id: str,
    event_type: str,
    decision: str,
    evidence_summary: dict[str, Any] | None = None,
    prev_record_hash: str = "genesis",
) -> dict[str, Any]:
    """Build a TraceEvent CTL record."""
    record: dict[str, Any] = {
        "record_type": "TraceEvent",
        "record_id": str(uuid.uuid4()),
        "prev_record_hash": prev_record_hash,
        "timestamp_utc": _utc_now_iso(),
        "session_id": session_id,
        "actor_id": actor_id,
        "event_type": event_type,
        "decision": decision,
    }
    if evidence_summary is not None:
        record["evidence_summary"] = evidence_summary
    return record


def build_commitment_record(
    *,
    actor_id: str,
    actor_role: str,
    commitment_type: str,
    subject_id: str,
    summary: str,
    subject_version: str | None = None,
    subject_hash: str | None = None,
    close_type: str | None = None,
    close_reason: str | None = None,
    references: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    prev_record_hash: str = "genesis",
) -> dict[str, Any]:
    """Build a CommitmentRecord CTL record."""
    record: dict[str, Any] = {
        "record_type": "CommitmentRecord",
        "record_id": str(uuid.uuid4()),
        "prev_record_hash": prev_record_hash,
        "timestamp_utc": _utc_now_iso(),
        "actor_id": actor_id,
        "actor_role": actor_role,
        "commitment_type": commitment_type,
        "subject_id": subject_id,
        "summary": summary,
    }
    if subject_version is not None:
        record["subject_version"] = subject_version
    if subject_hash is not None:
        record["subject_hash"] = subject_hash
    if close_type is not None:
        record["close_type"] = close_type
    if close_reason is not None:
        record["close_reason"] = close_reason
    if references:
        record["references"] = references
    if metadata:
        record["metadata"] = metadata
    return record


# ─────────────────────────────────────────────────────────────
# RBAC Helpers
# ─────────────────────────────────────────────────────────────


def can_govern_domain(user: dict[str, Any], domain_id: str) -> bool:
    """Check if a domain_authority user governs a specific domain."""
    role = user.get("role", "")
    if role == "root":
        return True
    if role != "domain_authority":
        return False
    governed = user.get("governed_modules") or []
    return domain_id in governed


def map_role_to_actor_role(role: str) -> str:
    """Map Lumina RBAC role to CTL actor_role enum value."""
    mapping = {
        "root": "administration",
        "domain_authority": "domain_authority",
        "it_support": "administration",
        "qa": "administration",
        "auditor": "administration",
        "user": "system",
    }
    return mapping.get(role, "system")
