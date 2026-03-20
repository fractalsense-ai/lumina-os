from __future__ import annotations

from pathlib import Path

import pytest

from lumina.persistence.filesystem import FilesystemPersistenceAdapter


@pytest.fixture
def fs_adapter(tmp_path: Path) -> FilesystemPersistenceAdapter:
    repo_root = Path(__file__).resolve().parents[1]
    log_dir = tmp_path / "ctl"
    return FilesystemPersistenceAdapter(repo_root=repo_root, log_dir=log_dir)


@pytest.mark.unit
def test_filesystem_user_crud(fs_adapter: FilesystemPersistenceAdapter) -> None:
    created = fs_adapter.create_user("u1", "alice", "salt:hash", "user", ["m1"])
    assert created["user_id"] == "u1"
    assert "password_hash" not in created

    by_id = fs_adapter.get_user("u1")
    assert by_id is not None
    assert by_id["password_hash"] == "salt:hash"

    by_username = fs_adapter.get_user_by_username("alice")
    assert by_username is not None
    assert by_username["user_id"] == "u1"

    listed = fs_adapter.list_users()
    assert len(listed) == 1
    assert listed[0]["username"] == "alice"
    assert "password_hash" not in listed[0]

    updated = fs_adapter.update_user_role("u1", "qa", ["m2"])
    assert updated is not None
    assert updated["role"] == "qa"
    assert updated["governed_modules"] == ["m2"]

    assert fs_adapter.deactivate_user("u1") is True
    assert fs_adapter.get_user("u1")["active"] is False


@pytest.mark.unit
def test_filesystem_session_state_roundtrip(fs_adapter: FilesystemPersistenceAdapter) -> None:
    assert fs_adapter.load_session_state("s1") is None
    fs_adapter.save_session_state("s1", {"turn_count": 3, "last_action": "task_presentation"})
    loaded = fs_adapter.load_session_state("s1")
    assert loaded == {"turn_count": 3, "last_action": "task_presentation"}


@pytest.mark.unit
def test_filesystem_ctl_chain_validation(fs_adapter: FilesystemPersistenceAdapter) -> None:
    sid = "s-chain"
    ledger = fs_adapter.get_log_ledger_path(sid)

    r1 = {
        "record_type": "TraceEvent",
        "record_id": "r1",
        "prev_record_hash": "genesis",
        "event_type": "turn",
    }
    fs_adapter.append_log_record(sid, r1, ledger)

    r2 = {
        "record_type": "TraceEvent",
        "record_id": "r2",
        "prev_record_hash": fs_adapter._hash_record(r1),
        "event_type": "turn",
    }
    fs_adapter.append_log_record(sid, r2, ledger)

    result = fs_adapter.validate_log_chain(sid)
    assert result["intact"] is True
    assert result["records_checked"] == 2
