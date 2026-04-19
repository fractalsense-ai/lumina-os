"""Tests for ScopedPersistenceAdapter and 3-tier ledger routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from lumina.persistence.filesystem import FilesystemPersistenceAdapter
from lumina.persistence.scoped import ScopedPersistenceAdapter


@pytest.fixture
def fs_adapter(tmp_path: Path) -> FilesystemPersistenceAdapter:
    repo_root = Path(__file__).resolve().parents[1]
    log_dir = tmp_path / "ctl"
    return FilesystemPersistenceAdapter(repo_root=repo_root, log_dir=log_dir)


@pytest.fixture
def scoped(fs_adapter: FilesystemPersistenceAdapter) -> ScopedPersistenceAdapter:
    return ScopedPersistenceAdapter(fs_adapter, domain_id="education")


# ── Tier path methods ────────────────────────────────────────


@pytest.mark.unit
def test_system_ledger_path(fs_adapter: FilesystemPersistenceAdapter) -> None:
    path = fs_adapter.get_system_ledger_path("admin")
    assert "system" in path
    assert path.endswith("session-admin.jsonl")


@pytest.mark.unit
def test_domain_ledger_path(fs_adapter: FilesystemPersistenceAdapter) -> None:
    path = fs_adapter.get_domain_ledger_path("education")
    assert "domains" in path and "education" in path
    assert path.endswith("domain.jsonl")


@pytest.mark.unit
def test_module_ledger_path(fs_adapter: FilesystemPersistenceAdapter) -> None:
    path = fs_adapter.get_module_ledger_path("education", "algebra-v1")
    assert "modules" in path and "algebra-v1" in path
    assert path.endswith("algebra-v1.jsonl")


# ── ScopedPersistenceAdapter routing ─────────────────────────


@pytest.mark.unit
def test_scoped_default_write_goes_to_domain_tier(scoped: ScopedPersistenceAdapter, fs_adapter: FilesystemPersistenceAdapter) -> None:
    record = {"record_type": "CommitmentRecord", "record_id": "r1"}
    scoped.append_log_record("admin", record)

    domain_path = Path(fs_adapter.get_domain_ledger_path("education"))
    assert domain_path.exists()
    records = fs_adapter._load_ledger_records(domain_path)
    assert len(records) == 1
    assert records[0]["record_id"] == "r1"


@pytest.mark.unit
def test_scoped_explicit_ledger_path_honoured(scoped: ScopedPersistenceAdapter, fs_adapter: FilesystemPersistenceAdapter) -> None:
    explicit_path = fs_adapter.get_system_ledger_path("admin")
    record = {"record_type": "TraceEvent", "record_id": "r2"}
    scoped.append_log_record("admin", record, ledger_path=explicit_path)

    system_path = Path(explicit_path)
    assert system_path.exists()
    records = fs_adapter._load_ledger_records(system_path)
    assert any(r["record_id"] == "r2" for r in records)


@pytest.mark.unit
def test_scoped_append_domain_log_record(scoped: ScopedPersistenceAdapter, fs_adapter: FilesystemPersistenceAdapter) -> None:
    record = {"record_type": "CommitmentRecord", "record_id": "r3"}
    scoped.append_domain_log_record("admin", record)

    domain_path = Path(fs_adapter.get_domain_ledger_path("education"))
    records = fs_adapter._load_ledger_records(domain_path)
    assert any(r["record_id"] == "r3" for r in records)


@pytest.mark.unit
def test_scoped_append_module_log_record(scoped: ScopedPersistenceAdapter, fs_adapter: FilesystemPersistenceAdapter) -> None:
    record = {"record_type": "TraceEvent", "record_id": "r4"}
    scoped.append_module_log_record("admin", record, module_id="algebra-v1")

    module_path = Path(fs_adapter.get_module_ledger_path("education", "algebra-v1"))
    assert module_path.exists()
    records = fs_adapter._load_ledger_records(module_path)
    assert any(r["record_id"] == "r4" for r in records)


@pytest.mark.unit
def test_scoped_module_write_requires_module_id(scoped: ScopedPersistenceAdapter) -> None:
    with pytest.raises(ValueError, match="module_id required"):
        scoped.append_module_log_record("admin", {"record_id": "bad"})


@pytest.mark.unit
def test_scoped_blocks_system_log_write(scoped: ScopedPersistenceAdapter) -> None:
    with pytest.raises(PermissionError, match="system-tier"):
        scoped.append_system_log_record({"record_id": "blocked"})


@pytest.mark.unit
def test_scoped_delegates_non_log_methods(scoped: ScopedPersistenceAdapter, fs_adapter: FilesystemPersistenceAdapter) -> None:
    """User reads are allowed but password_hash is stripped."""
    fs_adapter.create_user("u1", "alice", "salt:hash", "user", [])
    user = scoped.get_user("u1")
    assert user is not None
    assert user["username"] == "alice"
    assert "password_hash" not in user


@pytest.mark.unit
def test_scoped_strips_password_hash_get_user_by_username(scoped: ScopedPersistenceAdapter, fs_adapter: FilesystemPersistenceAdapter) -> None:
    fs_adapter.create_user("u2", "bob", "salt:hash", "user", [])
    user = scoped.get_user_by_username("bob")
    assert user is not None
    assert user["username"] == "bob"
    assert "password_hash" not in user


@pytest.mark.unit
def test_scoped_blocks_create_user(scoped: ScopedPersistenceAdapter) -> None:
    with pytest.raises(PermissionError):
        scoped.create_user("u1", "alice", "hash", "user", [])


@pytest.mark.unit
def test_scoped_blocks_deactivate_user(scoped: ScopedPersistenceAdapter, fs_adapter: FilesystemPersistenceAdapter) -> None:
    fs_adapter.create_user("u1", "alice", "salt:hash", "user", [])
    with pytest.raises(PermissionError):
        scoped.deactivate_user("u1")


@pytest.mark.unit
def test_scoped_blocks_update_user_password(scoped: ScopedPersistenceAdapter, fs_adapter: FilesystemPersistenceAdapter) -> None:
    fs_adapter.create_user("u1", "alice", "salt:hash", "user", [])
    with pytest.raises(PermissionError):
        scoped.update_user_password("u1", "new_hash")


@pytest.mark.unit
def test_scoped_blocks_unknown_method(scoped: ScopedPersistenceAdapter) -> None:
    with pytest.raises(AttributeError):
        scoped.totally_made_up_method()


# ── Tier isolation: records land in correct files ────────────


@pytest.mark.unit
def test_tier_isolation_system_vs_domain(fs_adapter: FilesystemPersistenceAdapter) -> None:
    sys_record = {"record_type": "TraceEvent", "record_id": "sys1", "event": "auth"}
    dom_record = {"record_type": "CommitmentRecord", "record_id": "dom1", "event": "rbac"}

    fs_adapter.append_log_record(
        "admin", sys_record,
        ledger_path=fs_adapter.get_system_ledger_path("admin"),
    )
    fs_adapter.append_log_record(
        "admin", dom_record,
        ledger_path=fs_adapter.get_domain_ledger_path("education"),
    )

    sys_path = Path(fs_adapter.get_system_ledger_path("admin"))
    dom_path = Path(fs_adapter.get_domain_ledger_path("education"))

    sys_records = fs_adapter._load_ledger_records(sys_path)
    dom_records = fs_adapter._load_ledger_records(dom_path)

    assert len(sys_records) == 1
    assert sys_records[0]["record_id"] == "sys1"
    assert len(dom_records) == 1
    assert dom_records[0]["record_id"] == "dom1"


# ── validate_log_chain covers tier directories ───────────────


@pytest.mark.unit
def test_validate_chain_includes_tier_ledgers(fs_adapter: FilesystemPersistenceAdapter) -> None:
    """validate_log_chain(None) checks all tier ledger files."""
    record = {
        "record_type": "CommitmentRecord",
        "record_id": "c1",
        "prev_record_hash": "genesis",
    }
    fs_adapter.append_log_record(
        "admin", record,
        ledger_path=fs_adapter.get_domain_ledger_path("education"),
    )

    result = fs_adapter.validate_log_chain()
    assert result["scope"] == "all"
    # Should find the domain ledger
    labels = [r["session_id"] for r in result["results"]]
    assert any("education" in label for label in labels)


# ── query_log_records scans tier directories ─────────────────


@pytest.mark.unit
def test_query_finds_records_in_tier_dirs(fs_adapter: FilesystemPersistenceAdapter) -> None:
    r1 = {"record_type": "CommitmentRecord", "record_id": "q1", "timestamp_utc": "2026-01-01T00:00:00Z"}
    r2 = {"record_type": "CommitmentRecord", "record_id": "q2", "timestamp_utc": "2026-01-02T00:00:00Z"}

    fs_adapter.append_log_record(
        "admin", r1,
        ledger_path=fs_adapter.get_system_ledger_path("admin"),
    )
    fs_adapter.append_log_record(
        "admin", r2,
        ledger_path=fs_adapter.get_domain_ledger_path("education"),
    )

    all_records = fs_adapter.query_log_records(record_type="CommitmentRecord", limit=100)
    ids = {r["record_id"] for r in all_records}
    assert "q1" in ids
    assert "q2" in ids


# ── _iter_all_ledger_paths ───────────────────────────────────


@pytest.mark.unit
def test_iter_all_ledger_paths(fs_adapter: FilesystemPersistenceAdapter) -> None:
    # Write records to system, domain, and module tiers
    fs_adapter.append_log_record(
        "admin", {"record_id": "a"},
        ledger_path=fs_adapter.get_system_ledger_path("admin"),
    )
    fs_adapter.append_log_record(
        "admin", {"record_id": "b"},
        ledger_path=fs_adapter.get_domain_ledger_path("education"),
    )
    fs_adapter.append_log_record(
        "admin", {"record_id": "c"},
        ledger_path=fs_adapter.get_module_ledger_path("education", "algebra-v1"),
    )

    paths = fs_adapter._iter_all_ledger_paths()
    path_strs = [str(p) for p in paths]
    assert any("system" in s for s in path_strs)
    assert any("education" in s and "domain.jsonl" in s for s in path_strs)
    assert any("algebra-v1" in s for s in path_strs)
