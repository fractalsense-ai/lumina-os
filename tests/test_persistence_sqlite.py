from __future__ import annotations

from pathlib import Path

import pytest

from lumina.persistence.sqlite import SQLitePersistenceAdapter


@pytest.fixture
def sqlite_adapter(tmp_path: Path) -> SQLitePersistenceAdapter:
    db_path = tmp_path / "lumina_test.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    repo_root = Path(__file__).resolve().parents[1]
    return SQLitePersistenceAdapter(repo_root=repo_root, database_url=db_url)


@pytest.mark.unit
def test_sqlite_user_crud(sqlite_adapter: SQLitePersistenceAdapter) -> None:
    created = sqlite_adapter.create_user("u1", "alice", "salt:hash", "user", ["m1"])
    assert created["user_id"] == "u1"
    assert created["username"] == "alice"
    assert "password_hash" not in created

    by_id = sqlite_adapter.get_user("u1")
    assert by_id is not None
    assert by_id["password_hash"] == "salt:hash"

    by_username = sqlite_adapter.get_user_by_username("alice")
    assert by_username is not None
    assert by_username["user_id"] == "u1"

    listed = sqlite_adapter.list_users()
    assert len(listed) == 1
    assert listed[0]["username"] == "alice"
    assert "password_hash" not in listed[0]

    updated = sqlite_adapter.update_user_role("u1", "qa", ["m2"])
    assert updated is not None
    assert updated["role"] == "qa"
    assert updated["governed_modules"] == ["m2"]

    assert sqlite_adapter.deactivate_user("u1") is True
    assert sqlite_adapter.get_user("u1")["active"] is False


@pytest.mark.unit
def test_sqlite_session_state_roundtrip(sqlite_adapter: SQLitePersistenceAdapter) -> None:
    assert sqlite_adapter.load_session_state("s1") is None
    sqlite_adapter.save_session_state("s1", {"turn_count": 2})
    assert sqlite_adapter.load_session_state("s1") == {"turn_count": 2}


@pytest.mark.unit
def test_sqlite_ctl_chain_validation(sqlite_adapter: SQLitePersistenceAdapter) -> None:
    sid = "s-chain"
    import hashlib
    import json

    def _hash_record(record: dict[str, str]) -> str:
        return hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    r1 = {
        "record_type": "TraceEvent",
        "record_id": "r1",
        "prev_record_hash": "genesis",
        "event_type": "turn",
    }
    sqlite_adapter.append_ctl_record(sid, r1)

    r2 = {
        "record_type": "TraceEvent",
        "record_id": "r2",
        "prev_record_hash": _hash_record(r1),
        "event_type": "turn",
    }
    sqlite_adapter.append_ctl_record(sid, r2)

    result = sqlite_adapter.validate_ctl_chain(sid)
    assert result["intact"] is True
    assert result["records_checked"] == 2
