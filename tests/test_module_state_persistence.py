"""Tests for per-actor per-module state persistence.

Covers CRUD round-trips on NullPersistenceAdapter, FilesystemPersistenceAdapter,
and SQLitePersistenceAdapter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────
# NullPersistenceAdapter
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestNullAdapterModuleState:
    """NullPersistenceAdapter in-memory module state CRUD."""

    def _make_adapter(self):
        from lumina.persistence.adapter import NullPersistenceAdapter
        return NullPersistenceAdapter()

    def test_load_missing_returns_none(self) -> None:
        adapter = self._make_adapter()
        assert adapter.load_module_state("u1", "algebra") is None

    def test_save_load_roundtrip(self) -> None:
        adapter = self._make_adapter()
        state = {"mastery": {"tier_1": 0.8}, "challenge": 0.5}
        adapter.save_module_state("u1", "algebra", state)
        loaded = adapter.load_module_state("u1", "algebra")
        assert loaded == state

    def test_upsert_overwrites(self) -> None:
        adapter = self._make_adapter()
        adapter.save_module_state("u1", "algebra", {"v": 1})
        adapter.save_module_state("u1", "algebra", {"v": 2})
        assert adapter.load_module_state("u1", "algebra") == {"v": 2}

    def test_list_module_states(self) -> None:
        adapter = self._make_adapter()
        adapter.save_module_state("u1", "algebra", {"a": 1})
        adapter.save_module_state("u1", "geometry", {"b": 2})
        keys = adapter.list_module_states("u1")
        assert sorted(keys) == ["algebra", "geometry"]

    def test_list_empty(self) -> None:
        adapter = self._make_adapter()
        assert adapter.list_module_states("u1") == []

    def test_delete_existing(self) -> None:
        adapter = self._make_adapter()
        adapter.save_module_state("u1", "algebra", {"a": 1})
        assert adapter.delete_module_state("u1", "algebra") is True
        assert adapter.load_module_state("u1", "algebra") is None

    def test_delete_missing(self) -> None:
        adapter = self._make_adapter()
        assert adapter.delete_module_state("u1", "algebra") is False

    def test_isolation_between_users(self) -> None:
        adapter = self._make_adapter()
        adapter.save_module_state("u1", "algebra", {"owner": "u1"})
        adapter.save_module_state("u2", "algebra", {"owner": "u2"})
        assert adapter.load_module_state("u1", "algebra")["owner"] == "u1"
        assert adapter.load_module_state("u2", "algebra")["owner"] == "u2"


# ─────────────────────────────────────────────────────────────
# FilesystemPersistenceAdapter
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestFilesystemAdapterModuleState:
    """FilesystemPersistenceAdapter file-backed module state CRUD."""

    def _make_adapter(self, tmp_path: Path):
        from lumina.persistence.filesystem import FilesystemPersistenceAdapter
        return FilesystemPersistenceAdapter(repo_root=_REPO_ROOT, log_dir=tmp_path / "log")

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        state = {"mastery": {"tier_1": 0.8}, "challenge": 0.5}
        adapter.save_module_state("u1", "algebra", state)
        loaded = adapter.load_module_state("u1", "algebra")
        assert loaded == state

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        assert adapter.load_module_state("u1", "algebra") is None

    def test_upsert_overwrites(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        adapter.save_module_state("u1", "algebra", {"v": 1})
        adapter.save_module_state("u1", "algebra", {"v": 2})
        assert adapter.load_module_state("u1", "algebra") == {"v": 2}

    def test_list_module_states(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        adapter.save_module_state("u1", "algebra", {"a": 1})
        adapter.save_module_state("u1", "geometry", {"b": 2})
        keys = adapter.list_module_states("u1")
        assert sorted(keys) == ["algebra", "geometry"]

    def test_delete_existing(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        adapter.save_module_state("u1", "algebra", {"a": 1})
        assert adapter.delete_module_state("u1", "algebra") is True
        assert adapter.load_module_state("u1", "algebra") is None

    def test_delete_missing(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        assert adapter.delete_module_state("u1", "algebra") is False

    def test_slash_in_module_key(self, tmp_path: Path) -> None:
        """Module keys with slashes (e.g. 'edu/algebra-level-1/v1') are safe."""
        adapter = self._make_adapter(tmp_path)
        key = "edu/algebra-level-1/v1"
        adapter.save_module_state("u1", key, {"ok": True})
        assert adapter.load_module_state("u1", key) == {"ok": True}
        assert key in adapter.list_module_states("u1")


# ─────────────────────────────────────────────────────────────
# SQLitePersistenceAdapter
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSQLiteAdapterModuleState:
    """SQLitePersistenceAdapter DB-backed module state CRUD."""

    def _make_adapter(self, tmp_path: Path):
        from lumina.persistence.sqlite import SQLitePersistenceAdapter
        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        return SQLitePersistenceAdapter(repo_root=_REPO_ROOT, database_url=db_url)

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        state = {"mastery": {"tier_1": 0.8}, "challenge": 0.5}
        adapter.save_module_state("u1", "algebra", state)
        loaded = adapter.load_module_state("u1", "algebra")
        assert loaded == state

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        assert adapter.load_module_state("u1", "algebra") is None

    def test_upsert_overwrites(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        adapter.save_module_state("u1", "algebra", {"v": 1})
        adapter.save_module_state("u1", "algebra", {"v": 2})
        assert adapter.load_module_state("u1", "algebra") == {"v": 2}

    def test_list_module_states(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        adapter.save_module_state("u1", "algebra", {"a": 1})
        adapter.save_module_state("u1", "geometry", {"b": 2})
        keys = adapter.list_module_states("u1")
        assert sorted(keys) == ["algebra", "geometry"]

    def test_delete_existing(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        adapter.save_module_state("u1", "algebra", {"a": 1})
        assert adapter.delete_module_state("u1", "algebra") is True
        assert adapter.load_module_state("u1", "algebra") is None

    def test_delete_missing(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        assert adapter.delete_module_state("u1", "algebra") is False

    def test_isolation_between_users(self, tmp_path: Path) -> None:
        adapter = self._make_adapter(tmp_path)
        adapter.save_module_state("u1", "algebra", {"owner": "u1"})
        adapter.save_module_state("u2", "algebra", {"owner": "u2"})
        assert adapter.load_module_state("u1", "algebra")["owner"] == "u1"
        assert adapter.load_module_state("u2", "algebra")["owner"] == "u2"
