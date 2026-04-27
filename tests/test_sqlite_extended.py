"""Extended tests for SQLitePersistenceAdapter: missing methods."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lumina.persistence.sqlite import SQLitePersistenceAdapter


@pytest.fixture
def db(tmp_path: Path) -> SQLitePersistenceAdapter:
    db_path = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    return SQLitePersistenceAdapter(repo_root=tmp_path, database_url=db_url)


# ── save_subject_profile ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_sqlite_save_subject_profile(db: SQLitePersistenceAdapter, tmp_path: Path) -> None:
    profile_path = str(tmp_path / "profiles" / "student.yaml")
    db.save_subject_profile(profile_path, {"student_id": "s1", "level": 3})
    assert Path(profile_path).exists()


# ── update_user_password ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_sqlite_update_user_password_success(db: SQLitePersistenceAdapter) -> None:
    db.create_user("u1", "alice", "old_hash", "user")
    result = db.update_user_password("u1", "new_hash")
    assert result is True
    user = db.get_user("u1")
    assert user is not None
    assert user["password_hash"] == "new_hash"


@pytest.mark.unit
def test_sqlite_update_user_password_not_found(db: SQLitePersistenceAdapter) -> None:
    assert db.update_user_password("nonexistent", "hash") is False


@pytest.mark.unit
def test_sqlite_update_user_role_not_found(db: SQLitePersistenceAdapter) -> None:
    result = db.update_user_role("nonexistent", "admin")
    assert result is None


@pytest.mark.unit
def test_sqlite_deactivate_user_not_found(db: SQLitePersistenceAdapter) -> None:
    assert db.deactivate_user("nonexistent") is False


# ── validate_log_chain all sessions ──────────────────────────────────────────


@pytest.mark.unit
def test_sqlite_validate_log_chain_all_sessions(db: SQLitePersistenceAdapter) -> None:
    for sid in ("s1", "s2"):
        db.append_log_record(sid, {
            "record_type": "TraceEvent", "record_id": f"r-{sid}",
            "prev_record_hash": "genesis", "event_type": "turn",
        })

    result = db.validate_log_chain()
    assert result["scope"] == "all"
    assert result["sessions_checked"] >= 2


@pytest.mark.unit
def test_sqlite_validate_log_chain_empty(db: SQLitePersistenceAdapter) -> None:
    result = db.validate_log_chain()
    assert result["scope"] == "all"
    assert result["intact"] is True


# ── has_policy_commitment ────────────────────────────────────────────────────


@pytest.mark.unit
def test_sqlite_has_policy_commitment_true(db: SQLitePersistenceAdapter) -> None:
    db.append_log_record("s1", {
        "record_type": "CommitmentRecord", "record_id": "c1",
        "prev_record_hash": "genesis",
        "subject_id": "domain-x", "subject_version": "1.0", "subject_hash": "hash_abc",
    })
    assert db.has_policy_commitment("domain-x", "1.0", "hash_abc") is True


@pytest.mark.unit
def test_sqlite_has_policy_commitment_false(db: SQLitePersistenceAdapter) -> None:
    assert db.has_policy_commitment("nonexistent", "1.0", "hash") is False


@pytest.mark.unit
def test_sqlite_has_policy_commitment_version_none(db: SQLitePersistenceAdapter) -> None:
    db.append_log_record("s1", {
        "record_type": "CommitmentRecord", "record_id": "c2",
        "prev_record_hash": "genesis",
        "subject_id": "domain-y", "subject_version": "2.0", "subject_hash": "hash_def",
    })
    assert db.has_policy_commitment("domain-y", None, "hash_def") is True


# ── has_system_physics_commitment ────────────────────────────────────────────


@pytest.mark.unit
def test_sqlite_has_system_physics_commitment_true(db: SQLitePersistenceAdapter) -> None:
    db.append_system_log_record({
        "record_type": "CommitmentRecord", "record_id": "sp1",
        "prev_record_hash": "genesis",
        "commitment_type": "system_physics_activation",
        "subject_hash": "physics_hash",
    })
    assert db.has_system_physics_commitment("physics_hash") is True


@pytest.mark.unit
def test_sqlite_has_system_physics_commitment_false(db: SQLitePersistenceAdapter) -> None:
    assert db.has_system_physics_commitment("missing_hash") is False


@pytest.mark.unit
def test_sqlite_has_system_physics_wrong_hash(db: SQLitePersistenceAdapter) -> None:
    db.append_system_log_record({
        "record_type": "CommitmentRecord", "record_id": "sp2",
        "prev_record_hash": "genesis",
        "commitment_type": "system_physics_activation",
        "subject_hash": "physics_hash_2",
    })
    assert db.has_system_physics_commitment("wrong_hash") is False


# ── query_log_records ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sqlite_query_log_records_all(db: SQLitePersistenceAdapter) -> None:
    sid = "s-query"
    for i in range(3):
        db.append_log_record(sid, {
            "record_type": "TraceEvent", "record_id": f"q{i}",
            "prev_record_hash": "genesis", "session_id": sid,
            "event_type": "turn",
        })
    records = db.query_log_records(session_id=sid)
    assert len(records) == 3


@pytest.mark.unit
def test_sqlite_query_log_records_by_record_type(db: SQLitePersistenceAdapter) -> None:
    sid = "s-filter"
    db.append_log_record(sid, {
        "record_type": "TraceEvent", "record_id": "f1",
        "prev_record_hash": "genesis", "session_id": sid,
    })
    db.append_log_record(sid, {
        "record_type": "CommitmentRecord", "record_id": "f2",
        "prev_record_hash": "genesis", "session_id": sid,
    })
    result = db.query_log_records(session_id=sid, record_type="TraceEvent")
    assert all(r["record_type"] == "TraceEvent" for r in result)


@pytest.mark.unit
def test_sqlite_query_log_records_by_event_type(db: SQLitePersistenceAdapter) -> None:
    sid = "s-event"
    db.append_log_record(sid, {
        "record_type": "TraceEvent", "record_id": "ev1",
        "prev_record_hash": "genesis", "session_id": sid,
        "event_type": "state_update",
    })
    result = db.query_log_records(session_id=sid, event_type="state_update")
    assert len(result) >= 1
    assert result[0]["event_type"] == "state_update"

    no_result = db.query_log_records(session_id=sid, event_type="other_event")
    assert no_result == []


@pytest.mark.unit
def test_sqlite_query_log_records_offset_limit(db: SQLitePersistenceAdapter) -> None:
    sid = "s-page"
    for i in range(5):
        db.append_log_record(sid, {
            "record_type": "TraceEvent", "record_id": f"p{i}",
            "prev_record_hash": "genesis", "session_id": sid,
        })
    page1 = db.query_log_records(session_id=sid, limit=2, offset=0)
    page2 = db.query_log_records(session_id=sid, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2


# ── list_log_sessions_summary ─────────────────────────────────────────────────


@pytest.mark.unit
def test_sqlite_list_log_sessions_summary_empty(db: SQLitePersistenceAdapter) -> None:
    result = db.list_log_sessions_summary()
    assert isinstance(result, list)


@pytest.mark.unit
def test_sqlite_list_log_sessions_summary_with_data(db: SQLitePersistenceAdapter) -> None:
    for sid in ("sum-s1", "sum-s2"):
        db.append_log_record(sid, {
            "record_type": "TraceEvent", "record_id": f"r-{sid}",
            "prev_record_hash": "genesis", "session_id": sid,
        })
    summaries = db.list_log_sessions_summary()
    session_ids = {s["session_id"] for s in summaries}
    assert "sum-s1" in session_ids
    assert "sum-s2" in session_ids
    for s in summaries:
        assert "record_count" in s
        assert s["record_count"] >= 1


# ── query_escalations ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sqlite_query_escalations_empty(db: SQLitePersistenceAdapter) -> None:
    result = db.query_escalations()
    assert isinstance(result, list)


@pytest.mark.unit
def test_sqlite_query_escalations_filter_status(db: SQLitePersistenceAdapter) -> None:
    sid = "s-esc"
    db.append_log_record(sid, {
        "record_type": "EscalationRecord", "record_id": "e1",
        "prev_record_hash": "genesis", "session_id": sid,
        "status": "pending", "model_pack_id": "edu",
    })
    pending = db.query_escalations(status="pending")
    assert any(r["record_id"] == "e1" for r in pending)
    resolved = db.query_escalations(status="resolved")
    assert not any(r["record_id"] == "e1" for r in resolved)


@pytest.mark.unit
def test_sqlite_query_escalations_filter_domain(db: SQLitePersistenceAdapter) -> None:
    sid = "s-esc2"
    db.append_log_record(sid, {
        "record_type": "EscalationRecord", "record_id": "e2",
        "prev_record_hash": "genesis", "session_id": sid,
        "status": "pending", "model_pack_id": "math",
    })
    result = db.query_escalations(domain_id="math")
    assert any(r["record_id"] == "e2" for r in result)
    other = db.query_escalations(domain_id="science")
    assert not any(r["record_id"] == "e2" for r in other)


# ── query_commitments ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sqlite_query_commitments(db: SQLitePersistenceAdapter) -> None:
    sid = "s-cm"
    db.append_log_record(sid, {
        "record_type": "CommitmentRecord", "record_id": "cm1",
        "prev_record_hash": "genesis", "session_id": sid,
        "subject_id": "domain-edu",
    })
    result = db.query_commitments("domain-edu")
    assert len(result) >= 1

    no_result = db.query_commitments("nonexistent")
    assert no_result == []
