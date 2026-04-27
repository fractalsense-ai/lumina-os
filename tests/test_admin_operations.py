"""Tests for lumina.system_log.admin_operations — System Log record builder functions.

Covers _utc_now_iso, _canonical_sha256 (dict path), build_trace_event,
build_commitment_record (all optional fields), can_govern_domain, and
map_role_to_actor_role.
"""
from __future__ import annotations

import datetime
import hashlib
import json

import pytest

from lumina.system_log.admin_operations import (
    _canonical_sha256,
    _utc_now_iso,
    build_commitment_record,
    build_domain_role_assignment,
    build_domain_role_revocation,
    build_trace_event,
    can_govern_domain,
    map_role_to_actor_role,
)


# ── _utc_now_iso ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_utc_now_iso_returns_string() -> None:
    result = _utc_now_iso()
    assert isinstance(result, str)
    # Must parse as ISO datetime with timezone
    dt = datetime.datetime.fromisoformat(result)
    assert dt.tzinfo is not None


# ── _canonical_sha256 ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_canonical_sha256_str_input() -> None:
    result = _canonical_sha256("hello")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert result == expected


@pytest.mark.unit
def test_canonical_sha256_dict_input() -> None:
    """Dict is serialised to canonical JSON before hashing."""
    val = {"b": 2, "a": 1}
    expected = hashlib.sha256(
        json.dumps(val, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert _canonical_sha256(val) == expected


@pytest.mark.unit
def test_canonical_sha256_dict_key_order_invariant() -> None:
    """Key order does not matter — canonical sort produces the same hash."""
    assert _canonical_sha256({"a": 1, "z": 2}) == _canonical_sha256({"z": 2, "a": 1})


# ── build_trace_event ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_build_trace_event_minimal() -> None:
    rec = build_trace_event(
        session_id="s1",
        actor_id="actor-001",
        event_type="turn",
        decision="proceed",
    )
    assert rec["record_type"] == "TraceEvent"
    assert rec["session_id"] == "s1"
    assert rec["actor_id"] == "actor-001"
    assert rec["event_type"] == "turn"
    assert rec["decision"] == "proceed"
    assert rec["prev_record_hash"] == "genesis"
    assert "evidence_summary" not in rec
    assert "record_id" in rec
    assert "timestamp_utc" in rec


@pytest.mark.unit
def test_build_trace_event_with_evidence_summary() -> None:
    rec = build_trace_event(
        session_id="s1",
        actor_id="actor-001",
        event_type="turn",
        decision="escalate",
        evidence_summary={"correctness": "incorrect", "frustration": 2},
        prev_record_hash="abc123dead",
    )
    assert rec["evidence_summary"] == {"correctness": "incorrect", "frustration": 2}
    assert rec["prev_record_hash"] == "abc123dead"


# ── build_commitment_record ───────────────────────────────────────────────────


@pytest.mark.unit
def test_build_commitment_record_minimal() -> None:
    rec = build_commitment_record(
        actor_id="actor-001",
        actor_role="admin",
        commitment_type="model_pack_activation",
        subject_id="education/algebra-v1",
        summary="Activated algebra module",
    )
    assert rec["record_type"] == "CommitmentRecord"
    assert rec["subject_id"] == "education/algebra-v1"
    assert rec["prev_record_hash"] == "genesis"
    assert "subject_version" not in rec
    assert "subject_hash" not in rec
    assert "close_type" not in rec
    assert "close_reason" not in rec
    assert "references" not in rec
    assert "metadata" not in rec


@pytest.mark.unit
def test_build_commitment_record_all_optional_fields() -> None:
    """All optional fields are included when provided."""
    rec = build_commitment_record(
        actor_id="actor-001",
        actor_role="admin",
        commitment_type="model_pack_rollback",
        subject_id="education/algebra-v1",
        summary="Rolled back due to defect",
        subject_version="2.1.0",
        subject_hash="deadbeef" * 8,
        close_type="rollback",
        close_reason="defective invariant in v2.1.0",
        references=["commitment-001", "commitment-002"],
        metadata={"note": "emergency rollback", "ticket": "INC-42"},
        prev_record_hash="prev-hash-value",
    )
    assert rec["subject_version"] == "2.1.0"
    assert rec["subject_hash"] == "deadbeef" * 8
    assert rec["close_type"] == "rollback"
    assert rec["close_reason"] == "defective invariant in v2.1.0"
    assert rec["references"] == ["commitment-001", "commitment-002"]
    assert rec["metadata"] == {"note": "emergency rollback", "ticket": "INC-42"}
    assert rec["prev_record_hash"] == "prev-hash-value"


@pytest.mark.unit
def test_build_commitment_record_subject_version_only() -> None:
    """subject_version alone (without subject_hash) is included."""
    rec = build_commitment_record(
        actor_id="actor-001",
        actor_role="admin",
        commitment_type="model_pack_activation",
        subject_id="edu/alg",
        summary="Activated",
        subject_version="1.0.0",
    )
    assert rec["subject_version"] == "1.0.0"
    assert "subject_hash" not in rec


@pytest.mark.unit
def test_build_commitment_record_subject_hash_only() -> None:
    """subject_hash alone (without subject_version) is included."""
    rec = build_commitment_record(
        actor_id="actor-001",
        actor_role="admin",
        commitment_type="model_pack_activation",
        subject_id="edu/alg",
        summary="Activated",
        subject_hash="abc123",
    )
    assert rec["subject_hash"] == "abc123"
    assert "subject_version" not in rec


# ── can_govern_domain ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_can_govern_domain_root_bypasses_check() -> None:
    assert can_govern_domain({"role": "root"}, "any-domain") is True


@pytest.mark.unit
def test_can_govern_domain_authority_match() -> None:
    user = {"role": "admin", "governed_modules": ["education", "agriculture"]}
    assert can_govern_domain(user, "education") is True
    assert can_govern_domain(user, "other") is False


@pytest.mark.unit
def test_can_govern_domain_non_authority_role() -> None:
    assert can_govern_domain({"role": "user"}, "education") is False


@pytest.mark.unit
def test_can_govern_domain_unrestricted_da() -> None:
    """DA with empty governed_modules and no domain_roles has unrestricted access."""
    user = {"role": "admin", "governed_modules": [], "domain_roles": {}}
    assert can_govern_domain(user, "education") is True
    assert can_govern_domain(user, "agriculture") is True


@pytest.mark.unit
def test_can_govern_domain_unrestricted_da_missing_keys() -> None:
    """DA with neither governed_modules nor domain_roles keys is unrestricted."""
    user = {"role": "admin"}
    assert can_govern_domain(user, "any-domain") is True


# ── map_role_to_actor_role ────────────────────────────────────────────────────


@pytest.mark.unit
def test_map_role_to_actor_role_known_roles() -> None:
    assert map_role_to_actor_role("root") == "administration"
    assert map_role_to_actor_role("admin") == "domain_authority"
    assert map_role_to_actor_role("super_admin") == "administration"
    assert map_role_to_actor_role("operator") == "administration"
    assert map_role_to_actor_role("half_operator") == "administration"
    assert map_role_to_actor_role("user") == "system"


@pytest.mark.unit
def test_map_role_to_actor_role_unknown_defaults_to_system() -> None:
    assert map_role_to_actor_role("unknown-role") == "system"
    assert map_role_to_actor_role("") == "system"


# ── build_domain_role_assignment ──────────────────────────────────────────────


@pytest.mark.unit
def test_build_domain_role_assignment_minimal() -> None:
    rec = build_domain_role_assignment(
        actor_id="admin-001",
        actor_role="administration",
        target_user_id="user-abc",
        module_id="education",
        domain_role="supervisor",
    )
    assert rec["record_type"] == "CommitmentRecord"
    assert rec["commitment_type"] == "domain_role_assignment"
    assert rec["subject_id"] == "user-abc"
    assert "education" in rec["summary"]
    assert "supervisor" in rec["summary"]
    meta = rec["metadata"]
    assert meta["target_user_id"] == "user-abc"
    assert meta["module_id"] == "education"
    assert meta["domain_role"] == "supervisor"
    assert rec["prev_record_hash"] == "genesis"
    assert "record_id" in rec
    assert "timestamp_utc" in rec


@pytest.mark.unit
def test_build_domain_role_assignment_custom_prev_hash() -> None:
    rec = build_domain_role_assignment(
        actor_id="admin-001",
        actor_role="administration",
        target_user_id="user-abc",
        module_id="education",
        domain_role="employee",
        prev_record_hash="deadbeef12345",
    )
    assert rec["prev_record_hash"] == "deadbeef12345"


# ── build_domain_role_revocation ──────────────────────────────────────────────


@pytest.mark.unit
def test_build_domain_role_revocation_minimal() -> None:
    rec = build_domain_role_revocation(
        actor_id="admin-001",
        actor_role="administration",
        target_user_id="user-abc",
        module_id="education",
        prev_role="supervisor",
    )
    assert rec["record_type"] == "CommitmentRecord"
    assert rec["commitment_type"] == "domain_role_revocation"
    assert rec["subject_id"] == "user-abc"
    assert "supervisor" in rec["summary"]
    assert "education" in rec["summary"]
    meta = rec["metadata"]
    assert meta["target_user_id"] == "user-abc"
    assert meta["module_id"] == "education"
    assert meta["prev_role"] == "supervisor"
    assert rec["prev_record_hash"] == "genesis"


@pytest.mark.unit
def test_build_domain_role_revocation_custom_prev_hash() -> None:
    rec = build_domain_role_revocation(
        actor_id="admin-001",
        actor_role="administration",
        target_user_id="user-abc",
        module_id="education",
        prev_role="employee",
        prev_record_hash="abc999xyz",
    )
    assert rec["prev_record_hash"] == "abc999xyz"
