"""Extended tests for lumina.persistence.filesystem: YAML serializer, missing methods."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from lumina.persistence.filesystem import (
    FilesystemPersistenceAdapter,
    _dump_yaml,
    _yaml_lines,
    _yaml_scalar,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def adapter(tmp_path: Path) -> FilesystemPersistenceAdapter:
    return FilesystemPersistenceAdapter(repo_root=REPO_ROOT, log_dir=tmp_path / "ctl")


# ── _yaml_scalar ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_yaml_scalar_none() -> None:
    assert _yaml_scalar(None) == "null"


@pytest.mark.unit
def test_yaml_scalar_bool_true() -> None:
    assert _yaml_scalar(True) == "true"


@pytest.mark.unit
def test_yaml_scalar_bool_false() -> None:
    assert _yaml_scalar(False) == "false"


@pytest.mark.unit
def test_yaml_scalar_int() -> None:
    assert _yaml_scalar(42) == "42"


@pytest.mark.unit
def test_yaml_scalar_float() -> None:
    result = _yaml_scalar(3.14)
    assert "3.14" in result


@pytest.mark.unit
def test_yaml_scalar_simple_string() -> None:
    assert _yaml_scalar("hello") == "hello"


@pytest.mark.unit
def test_yaml_scalar_empty_string_quoted() -> None:
    result = _yaml_scalar("")
    assert result.startswith('"') or result == '""'


@pytest.mark.unit
def test_yaml_scalar_string_with_leading_colon() -> None:
    result = _yaml_scalar(":value")
    assert result.startswith('"')


@pytest.mark.unit
def test_yaml_scalar_reserved_word() -> None:
    # "true" as string should be quoted
    result = _yaml_scalar("true")
    assert result.startswith('"')


@pytest.mark.unit
def test_yaml_scalar_string_with_newline() -> None:
    result = _yaml_scalar("line1\nline2")
    assert '"' in result


@pytest.mark.unit
def test_yaml_scalar_string_with_colon_space() -> None:
    result = _yaml_scalar("key: value")
    assert result.startswith('"')


@pytest.mark.unit
def test_yaml_scalar_string_leading_space() -> None:
    result = _yaml_scalar("  leading")
    assert result.startswith('"')


# ── _yaml_lines ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_yaml_lines_simple_dict() -> None:
    lines = _yaml_lines({"name": "Alice", "age": 30}, 0)
    assert any("name: Alice" in l for l in lines)
    assert any("age: 30" in l for l in lines)


@pytest.mark.unit
def test_yaml_lines_empty_dict() -> None:
    lines = _yaml_lines({}, 0)
    assert lines == ["{}"]


@pytest.mark.unit
def test_yaml_lines_nested_dict() -> None:
    lines = _yaml_lines({"outer": {"inner": "value"}}, 0)
    assert any("outer:" in l for l in lines)
    assert any("inner: value" in l for l in lines)


@pytest.mark.unit
def test_yaml_lines_dict_with_list() -> None:
    lines = _yaml_lines({"items": ["a", "b"]}, 0)
    assert any("items:" in l for l in lines)
    assert any("- a" in l for l in lines)


@pytest.mark.unit
def test_yaml_lines_dict_with_empty_list() -> None:
    lines = _yaml_lines({"items": []}, 0)
    assert any("items: []" in l for l in lines)


@pytest.mark.unit
def test_yaml_lines_dict_with_empty_dict_value() -> None:
    lines = _yaml_lines({"nested": {}}, 0)
    assert any("nested: {}" in l for l in lines)


@pytest.mark.unit
def test_yaml_lines_list_of_dicts() -> None:
    lines = _yaml_lines([{"key": "val1"}, {"key": "val2"}], 0)
    assert any("key: val1" in l for l in lines)
    assert any("key: val2" in l for l in lines)


@pytest.mark.unit
def test_yaml_lines_list_of_scalars() -> None:
    lines = _yaml_lines(["a", "b", "c"], 0)
    assert any("- a" in l for l in lines)


@pytest.mark.unit
def test_yaml_lines_scalar() -> None:
    lines = _yaml_lines("hello", 0)
    assert lines == ["hello"]


# ── _dump_yaml ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_dump_yaml_ends_with_newline() -> None:
    result = _dump_yaml({"key": "value"})
    assert result.endswith("\n")


@pytest.mark.unit
def test_dump_yaml_roundtrip() -> None:
    data = {"name": "test", "count": 5, "active": True, "tags": ["a", "b"]}
    yaml_str = _dump_yaml(data)
    assert "name: test" in yaml_str
    assert "count: 5" in yaml_str
    assert "active: true" in yaml_str


# ── save_subject_profile ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_save_subject_profile_creates_file(adapter: FilesystemPersistenceAdapter, tmp_path: Path) -> None:
    profile_path = str(tmp_path / "profiles" / "student.yaml")
    data = {"student_id": "s1", "mastered": ["algebra"], "level": 3}
    adapter.save_subject_profile(profile_path, data)
    assert Path(profile_path).exists()


@pytest.mark.unit
def test_save_subject_profile_content(adapter: FilesystemPersistenceAdapter, tmp_path: Path) -> None:
    profile_path = str(tmp_path / "profile.yaml")
    data = {"name": "learner", "score": 90}
    adapter.save_subject_profile(profile_path, data)
    content = Path(profile_path).read_text(encoding="utf-8")
    assert "name: learner" in content
    assert "score: 90" in content


# ── get_log_ledger_path with domain_id ────────────────────────────────────────


@pytest.mark.unit
def test_get_log_ledger_path_with_domain_id(adapter: FilesystemPersistenceAdapter) -> None:
    path = adapter.get_log_ledger_path("session-1", domain_id="edu")
    assert "session-1" in path
    assert "edu" in path


@pytest.mark.unit
def test_get_log_ledger_path_without_domain_id(adapter: FilesystemPersistenceAdapter) -> None:
    path = adapter.get_log_ledger_path("session-1")
    assert "session-1" in path
    assert path.endswith(".jsonl")


# ── validate_log_chain all sessions ──────────────────────────────────────────


@pytest.mark.unit
def test_validate_log_chain_all_sessions(adapter: FilesystemPersistenceAdapter) -> None:
    for sid in ("s1", "s2"):
        ledger = adapter.get_log_ledger_path(sid)
        r = {"record_type": "TraceEvent", "record_id": f"r-{sid}",
             "prev_record_hash": "genesis", "event_type": "turn"}
        adapter.append_log_record(sid, r, ledger)

    result = adapter.validate_log_chain()
    assert result["scope"] == "all"
    assert result["sessions_checked"] >= 2
    assert "intact" in result


@pytest.mark.unit
def test_validate_log_chain_no_sessions(adapter: FilesystemPersistenceAdapter) -> None:
    result = adapter.validate_log_chain()
    assert result["scope"] == "all"
    # With no ledger files on disk, nothing to check
    assert result["sessions_checked"] == 0


# ── has_policy_commitment ────────────────────────────────────────────────────


@pytest.mark.unit
def test_has_policy_commitment_true(adapter: FilesystemPersistenceAdapter) -> None:
    sid = "s-commit"
    record: dict[str, Any] = {
        "record_type": "CommitmentRecord",
        "record_id": "c1",
        "prev_record_hash": "genesis",
        "subject_id": "domain-123",
        "subject_version": "1.0.0",
        "subject_hash": "abc123hashed",
        "commitment_type": "domain_pack_activation",
    }
    adapter.append_log_record(sid, record)
    assert adapter.has_policy_commitment("domain-123", "1.0.0", "abc123hashed") is True


@pytest.mark.unit
def test_has_policy_commitment_false(adapter: FilesystemPersistenceAdapter) -> None:
    assert adapter.has_policy_commitment("nonexistent", "1.0.0", "hash") is False


@pytest.mark.unit
def test_has_policy_commitment_version_none(adapter: FilesystemPersistenceAdapter) -> None:
    sid = "s-commit2"
    record: dict[str, Any] = {
        "record_type": "CommitmentRecord",
        "record_id": "c2",
        "prev_record_hash": "genesis",
        "subject_id": "domain-x",
        "subject_version": "2.0",
        "subject_hash": "deadbeef",
        "commitment_type": "domain_pack_activation",
    }
    adapter.append_log_record(sid, record)
    # With version=None, should match any version
    assert adapter.has_policy_commitment("domain-x", None, "deadbeef") is True


# ── has_system_physics_commitment ────────────────────────────────────────────


@pytest.mark.unit
def test_has_system_physics_commitment_false_empty(adapter: FilesystemPersistenceAdapter) -> None:
    assert adapter.has_system_physics_commitment("any_hash") is False


@pytest.mark.unit
def test_has_system_physics_commitment_true(adapter: FilesystemPersistenceAdapter) -> None:
    record: dict[str, Any] = {
        "record_type": "CommitmentRecord",
        "record_id": "sp1",
        "prev_record_hash": "genesis",
        "commitment_type": "system_physics_activation",
        "subject_hash": "physics_hash_abc",
    }
    adapter.append_system_log_record(record)
    assert adapter.has_system_physics_commitment("physics_hash_abc") is True


@pytest.mark.unit
def test_has_system_physics_commitment_wrong_hash(adapter: FilesystemPersistenceAdapter) -> None:
    record: dict[str, Any] = {
        "record_type": "CommitmentRecord",
        "record_id": "sp2",
        "prev_record_hash": "genesis",
        "commitment_type": "system_physics_activation",
        "subject_hash": "physics_hash_abc",
    }
    adapter.append_system_log_record(record)
    assert adapter.has_system_physics_commitment("wrong_hash") is False


# ── update_user_password ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_update_user_password_success(adapter: FilesystemPersistenceAdapter) -> None:
    adapter.create_user("u1", "alice", "old_hash", "user")
    result = adapter.update_user_password("u1", "new_hash")
    assert result is True
    user = adapter.get_user("u1")
    assert user is not None
    assert user["password_hash"] == "new_hash"


@pytest.mark.unit
def test_update_user_password_not_found(adapter: FilesystemPersistenceAdapter) -> None:
    assert adapter.update_user_password("nonexistent", "hash") is False


@pytest.mark.unit
def test_update_user_role_not_found(adapter: FilesystemPersistenceAdapter) -> None:
    result = adapter.update_user_role("nonexistent", "admin")
    assert result is None


@pytest.mark.unit
def test_deactivate_user_not_found(adapter: FilesystemPersistenceAdapter) -> None:
    assert adapter.deactivate_user("nonexistent") is False


# ── query_log_records ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_log_records_all(adapter: FilesystemPersistenceAdapter) -> None:
    sid = "s-query"
    r1: dict[str, Any] = {
        "record_type": "TraceEvent", "record_id": "q1",
        "prev_record_hash": "genesis", "session_id": sid,
        "event_type": "turn", "timestamp_utc": "2024-01-01T00:00:00Z",
    }
    r2: dict[str, Any] = {
        "record_type": "EscalationRecord", "record_id": "q2",
        "prev_record_hash": adapter._hash_record(r1), "session_id": sid,
        "timestamp_utc": "2024-01-01T00:01:00Z",
    }
    adapter.append_log_record(sid, r1)
    adapter.append_log_record(sid, r2)

    all_records = adapter.query_log_records(session_id=sid)
    assert len(all_records) == 2


@pytest.mark.unit
def test_query_log_records_filter_by_type(adapter: FilesystemPersistenceAdapter) -> None:
    sid = "s-filter"
    r1: dict[str, Any] = {
        "record_type": "TraceEvent", "record_id": "f1",
        "prev_record_hash": "genesis", "session_id": sid,
        "timestamp_utc": "2024-01-01T00:00:00Z",
    }
    r2: dict[str, Any] = {
        "record_type": "CommitmentRecord", "record_id": "f2",
        "prev_record_hash": adapter._hash_record(r1), "session_id": sid,
        "timestamp_utc": "2024-01-01T00:01:00Z",
    }
    adapter.append_log_record(sid, r1)
    adapter.append_log_record(sid, r2)

    trace_records = adapter.query_log_records(session_id=sid, record_type="TraceEvent")
    assert len(trace_records) == 1
    assert trace_records[0]["record_id"] == "f1"


@pytest.mark.unit
def test_query_log_records_filter_by_event_type(adapter: FilesystemPersistenceAdapter) -> None:
    sid = "s-event"
    r: dict[str, Any] = {
        "record_type": "TraceEvent", "record_id": "ev1",
        "prev_record_hash": "genesis", "session_id": sid,
        "event_type": "state_update", "timestamp_utc": "2024-01-01T00:00:00Z",
    }
    adapter.append_log_record(sid, r)
    result = adapter.query_log_records(session_id=sid, event_type="state_update")
    assert len(result) == 1
    result_none = adapter.query_log_records(session_id=sid, event_type="other_event")
    assert result_none == []


@pytest.mark.unit
def test_query_log_records_with_domain_id(adapter: FilesystemPersistenceAdapter) -> None:
    sid = "s-domain"
    domain = "edu-domain"
    ledger_path = adapter.get_log_ledger_path(sid, domain_id=domain)
    r: dict[str, Any] = {
        "record_type": "TraceEvent", "record_id": "d1",
        "prev_record_hash": "genesis", "session_id": sid,
        "timestamp_utc": "2024-01-01T00:00:00Z",
    }
    adapter.append_log_record(sid, r, ledger_path)

    result = adapter.query_log_records(session_id=sid, domain_id=domain)
    assert len(result) >= 1


@pytest.mark.unit
def test_query_log_records_offset_limit(adapter: FilesystemPersistenceAdapter) -> None:
    sid = "s-page"
    for i in range(5):
        r: dict[str, Any] = {
            "record_type": "TraceEvent", "record_id": f"p{i}",
            "prev_record_hash": "genesis" if i == 0 else "prev",
            "session_id": sid,
            "timestamp_utc": f"2024-01-01T00:0{i}:00Z",
        }
        adapter.append_log_record(sid, r)

    page1 = adapter.query_log_records(session_id=sid, limit=2, offset=0)
    page2 = adapter.query_log_records(session_id=sid, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["record_id"] != page2[0]["record_id"]


# ── list_log_sessions_summary ────────────────────────────────────────────────


@pytest.mark.unit
def test_list_log_sessions_summary_empty(adapter: FilesystemPersistenceAdapter) -> None:
    result = adapter.list_log_sessions_summary()
    assert isinstance(result, list)


@pytest.mark.unit
def test_list_log_sessions_summary_with_records(adapter: FilesystemPersistenceAdapter) -> None:
    for sid in ("summary-s1", "summary-s2"):
        r: dict[str, Any] = {
            "record_type": "TraceEvent", "record_id": f"r-{sid}",
            "prev_record_hash": "genesis", "session_id": sid,
            "timestamp_utc": "2024-01-01T00:00:00Z",
        }
        adapter.append_log_record(sid, r)

    summaries = adapter.list_log_sessions_summary()
    assert len(summaries) >= 2
    session_ids = {s["session_id"] for s in summaries}
    assert "summary-s1" in session_ids
    assert "summary-s2" in session_ids
    for s in summaries:
        assert "record_count" in s
        assert s["record_count"] >= 1


# ── query_escalations ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_escalations_empty(adapter: FilesystemPersistenceAdapter) -> None:
    result = adapter.query_escalations()
    assert isinstance(result, list)


@pytest.mark.unit
def test_query_escalations_filter_status(adapter: FilesystemPersistenceAdapter) -> None:
    sid = "s-esc"
    r: dict[str, Any] = {
        "record_type": "EscalationRecord", "record_id": "e1",
        "prev_record_hash": "genesis", "session_id": sid,
        "status": "pending", "domain_pack_id": "edu",
        "timestamp_utc": "2024-01-01T00:00:00Z",
    }
    adapter.append_log_record(sid, r)

    pending = adapter.query_escalations(status="pending")
    assert any(rec["record_id"] == "e1" for rec in pending)
    resolved = adapter.query_escalations(status="resolved")
    assert not any(rec["record_id"] == "e1" for rec in resolved)


# ── query_commitments ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_commitments(adapter: FilesystemPersistenceAdapter) -> None:
    sid = "s-commitments"
    r: dict[str, Any] = {
        "record_type": "CommitmentRecord", "record_id": "cm1",
        "prev_record_hash": "genesis", "session_id": sid,
        "subject_id": "domain-abc", "timestamp_utc": "2024-01-01T00:00:00Z",
    }
    adapter.append_log_record(sid, r)

    result = adapter.query_commitments("domain-abc")
    assert len(result) >= 1
    assert result[0]["subject_id"] == "domain-abc"

    no_result = adapter.query_commitments("nonexistent-subject")
    assert no_result == []
