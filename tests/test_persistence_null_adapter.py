from __future__ import annotations

import pytest

from lumina.persistence.adapter import NullPersistenceAdapter


@pytest.mark.unit
def test_null_adapter_user_crud_and_deactivate() -> None:
    adapter = NullPersistenceAdapter()

    created = adapter.create_user("u1", "alice", "salt:hash", "user", ["m1"])
    assert created["user_id"] == "u1"
    assert created["username"] == "alice"
    assert created["role"] == "user"
    assert created["active"] is True
    assert "password_hash" not in created

    by_id = adapter.get_user("u1")
    assert by_id is not None
    assert by_id["password_hash"] == "salt:hash"

    by_username = adapter.get_user_by_username("alice")
    assert by_username is not None
    assert by_username["user_id"] == "u1"

    updated = adapter.update_user_role("u1", "qa", ["m2"])
    assert updated is not None
    assert updated["role"] == "qa"
    assert updated["governed_modules"] == ["m2"]

    assert adapter.deactivate_user("u1") is True
    assert adapter.get_user("u1")["active"] is False


@pytest.mark.unit
def test_null_adapter_session_state_roundtrip() -> None:
    adapter = NullPersistenceAdapter()

    assert adapter.load_session_state("s1") is None
    adapter.save_session_state("s1", {"turn_count": 2})
    loaded = adapter.load_session_state("s1")
    assert loaded == {"turn_count": 2}


@pytest.mark.unit
def test_null_adapter_validate_ctl_shape() -> None:
    adapter = NullPersistenceAdapter()

    all_result = adapter.validate_ctl_chain()
    assert all_result["scope"] == "all"
    assert all_result["intact"] is True

    one_result = adapter.validate_ctl_chain("session-x")
    assert one_result["scope"] == "session"
    assert one_result["session_id"] == "session-x"
    assert one_result["intact"] is True
