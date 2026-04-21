"""Tests for NullPersistenceAdapter covering previously uncovered branches."""
import pytest

from lumina.persistence.adapter import NullPersistenceAdapter


@pytest.mark.unit
def test_get_log_ledger_path_with_domain_id():
    adapter = NullPersistenceAdapter()
    result = adapter.get_log_ledger_path("sess-123", domain_id="math")
    assert result == "session-sess-123-math.jsonl"


@pytest.mark.unit
def test_get_log_ledger_path_without_domain_id():
    adapter = NullPersistenceAdapter()
    result = adapter.get_log_ledger_path("sess-123")
    assert result == "session-sess-123.jsonl"


@pytest.mark.unit
def test_get_log_ledger_path_domain_id_none_explicit():
    adapter = NullPersistenceAdapter()
    result = adapter.get_log_ledger_path("sess-456", domain_id=None)
    assert result == "session-sess-456.jsonl"


@pytest.mark.unit
def test_load_session_state_existing():
    adapter = NullPersistenceAdapter()
    adapter.save_session_state("s1", {"key": "value", "count": 42})
    result = adapter.load_session_state("s1")
    assert result == {"key": "value", "count": 42}


@pytest.mark.unit
def test_load_session_state_missing_returns_none():
    adapter = NullPersistenceAdapter()
    result = adapter.load_session_state("nonexistent")
    assert result is None


@pytest.mark.unit
def test_load_session_state_returns_copy():
    """Mutating the returned dict should not affect stored state."""
    adapter = NullPersistenceAdapter()
    adapter.save_session_state("s2", {"x": 1})
    result = adapter.load_session_state("s2")
    result["x"] = 999
    assert adapter.load_session_state("s2") == {"x": 1}


@pytest.mark.unit
def test_update_user_role_not_found_returns_none():
    adapter = NullPersistenceAdapter()
    result = adapter.update_user_role("nonexistent-user", "operator")
    assert result is None


@pytest.mark.unit
def test_update_user_role_found_updates_and_returns_record():
    adapter = NullPersistenceAdapter()
    adapter.create_user("u1", "alice", "hash_abc", "learner")
    result = adapter.update_user_role("u1", "admin", governed_modules=["math"])
    assert result is not None
    assert result["role"] == "admin"
    assert result["governed_modules"] == ["math"]
    assert "password_hash" not in result


@pytest.mark.unit
def test_deactivate_user_not_found_returns_false():
    adapter = NullPersistenceAdapter()
    result = adapter.deactivate_user("ghost-user")
    assert result is False


@pytest.mark.unit
def test_deactivate_user_found_returns_true():
    adapter = NullPersistenceAdapter()
    adapter.create_user("u2", "bob", "hash_xyz", "learner")
    result = adapter.deactivate_user("u2")
    assert result is True
    user = adapter.get_user("u2")
    assert user["active"] is False


@pytest.mark.unit
def test_update_user_password_not_found_returns_false():
    adapter = NullPersistenceAdapter()
    result = adapter.update_user_password("ghost-user", "new_hash")
    assert result is False


@pytest.mark.unit
def test_update_user_password_found_returns_true():
    adapter = NullPersistenceAdapter()
    adapter.create_user("u3", "carol", "old_hash", "admin")
    result = adapter.update_user_password("u3", "new_hash")
    assert result is True
    user = adapter.get_user("u3")
    assert user["password_hash"] == "new_hash"


@pytest.mark.unit
def test_create_user_excludes_password_hash_from_return():
    adapter = NullPersistenceAdapter()
    result = adapter.create_user("u4", "dave", "secret", "learner")
    assert "password_hash" not in result
    assert result["user_id"] == "u4"
    assert result["username"] == "dave"
    assert result["role"] == "learner"


@pytest.mark.unit
def test_get_user_by_username_found():
    adapter = NullPersistenceAdapter()
    adapter.create_user("u5", "eve", "hash", "admin")
    result = adapter.get_user_by_username("eve")
    assert result is not None
    assert result["user_id"] == "u5"


@pytest.mark.unit
def test_get_user_by_username_not_found():
    adapter = NullPersistenceAdapter()
    result = adapter.get_user_by_username("nobody")
    assert result is None


@pytest.mark.unit
def test_list_users_excludes_password_hash():
    adapter = NullPersistenceAdapter()
    adapter.create_user("u6", "frank", "secret", "learner")
    users = adapter.list_users()
    assert len(users) == 1
    assert "password_hash" not in users[0]


@pytest.mark.unit
def test_validate_log_chain_with_session_id():
    adapter = NullPersistenceAdapter()
    result = adapter.validate_log_chain(session_id="sess-99")
    assert result["scope"] == "session"
    assert result["session_id"] == "sess-99"
    assert result["intact"] is True


@pytest.mark.unit
def test_validate_log_chain_all_sessions():
    adapter = NullPersistenceAdapter()
    result = adapter.validate_log_chain()
    assert result["scope"] == "all"
    assert result["intact"] is True


# ── update_user_domain_roles ──────────────────────────────────────────────────


@pytest.mark.unit
def test_update_user_domain_roles_not_found_returns_none():
    adapter = NullPersistenceAdapter()
    result = adapter.update_user_domain_roles("ghost-id", {"education": "supervisor"})
    assert result is None


@pytest.mark.unit
def test_update_user_domain_roles_sets_new_entry():
    adapter = NullPersistenceAdapter()
    adapter.create_user("u10", "grace", "hash", "user")
    result = adapter.update_user_domain_roles("u10", {"education": "supervisor"})
    assert result is not None
    assert result["domain_roles"] == {"education": "supervisor"}
    assert "password_hash" not in result


@pytest.mark.unit
def test_update_user_domain_roles_merges_with_existing():
    adapter = NullPersistenceAdapter()
    adapter.create_user("u11", "henry", "hash", "user")
    adapter.update_user_domain_roles("u11", {"education": "supervisor"})
    result = adapter.update_user_domain_roles("u11", {"agriculture": "employee"})
    assert result is not None
    assert result["domain_roles"] == {"education": "supervisor", "agriculture": "employee"}


@pytest.mark.unit
def test_update_user_domain_roles_overwrites_same_module():
    adapter = NullPersistenceAdapter()
    adapter.create_user("u12", "iris", "hash", "user")
    adapter.update_user_domain_roles("u12", {"education": "supervisor"})
    result = adapter.update_user_domain_roles("u12", {"education": "employee"})
    assert result is not None
    assert result["domain_roles"]["education"] == "employee"
