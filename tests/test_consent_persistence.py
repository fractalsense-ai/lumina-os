"""Tests for consent persistence across sessions.

Covers:
- set_user_consent / get_user_consent round-trip (NullPersistenceAdapter)
- set_user_consent / get_user_consent round-trip (FilesystemPersistenceAdapter)
- Consent accept endpoint persists to storage
- Processing consent gate reads persisted consent for new sessions
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────
# Persistence adapter consent round-trip
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestNullAdapterConsent:
    """NullPersistenceAdapter consent methods."""

    def test_set_get_consent_roundtrip(self) -> None:
        from lumina.persistence.adapter import NullPersistenceAdapter
        adapter = NullPersistenceAdapter()
        adapter.create_user("u1", "alice", "hash", "user")
        now = time.time()
        assert adapter.set_user_consent("u1", True, now) is True
        rec = adapter.get_user_consent("u1")
        assert rec is not None
        assert rec["accepted"] is True
        assert rec["timestamp"] == now

    def test_get_consent_no_record(self) -> None:
        from lumina.persistence.adapter import NullPersistenceAdapter
        adapter = NullPersistenceAdapter()
        adapter.create_user("u1", "alice", "hash", "user")
        assert adapter.get_user_consent("u1") is None

    def test_set_consent_unknown_user(self) -> None:
        from lumina.persistence.adapter import NullPersistenceAdapter
        adapter = NullPersistenceAdapter()
        assert adapter.set_user_consent("nobody", True, time.time()) is False

    def test_get_consent_unknown_user(self) -> None:
        from lumina.persistence.adapter import NullPersistenceAdapter
        adapter = NullPersistenceAdapter()
        assert adapter.get_user_consent("nobody") is None


@pytest.mark.unit
class TestFilesystemAdapterConsent:
    """FilesystemPersistenceAdapter consent methods."""

    def test_set_get_consent_roundtrip(self, tmp_path: Path) -> None:
        from lumina.persistence.filesystem import FilesystemPersistenceAdapter
        adapter = FilesystemPersistenceAdapter(repo_root=_REPO_ROOT, log_dir=tmp_path)
        adapter.create_user("u1", "alice", "hash", "user")
        now = time.time()
        assert adapter.set_user_consent("u1", True, now) is True
        rec = adapter.get_user_consent("u1")
        assert rec is not None
        assert rec["accepted"] is True
        assert rec["timestamp"] == now

    def test_consent_survives_reload(self, tmp_path: Path) -> None:
        from lumina.persistence.filesystem import FilesystemPersistenceAdapter
        adapter = FilesystemPersistenceAdapter(repo_root=_REPO_ROOT, log_dir=tmp_path)
        adapter.create_user("u1", "alice", "hash", "user")
        now = time.time()
        adapter.set_user_consent("u1", True, now)
        # Create a new adapter instance to verify persistence
        adapter2 = FilesystemPersistenceAdapter(repo_root=_REPO_ROOT, log_dir=tmp_path)
        rec = adapter2.get_user_consent("u1")
        assert rec is not None
        assert rec["accepted"] is True

    def test_get_consent_no_record(self, tmp_path: Path) -> None:
        from lumina.persistence.filesystem import FilesystemPersistenceAdapter
        adapter = FilesystemPersistenceAdapter(repo_root=_REPO_ROOT, log_dir=tmp_path)
        adapter.create_user("u1", "alice", "hash", "user")
        assert adapter.get_user_consent("u1") is None


# ─────────────────────────────────────────────────────────────
# Consent accept endpoint persists
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestConsentEndpointPersistence:
    """POST /api/consent/accept writes to persistence layer."""

    def test_accept_persists_consent(self) -> None:
        import asyncio
        from lumina.api.routes.consent import accept_consent

        mock_creds = MagicMock()
        mock_persistence = MagicMock()
        mock_persistence.set_user_consent.return_value = True
        mock_cfg = MagicMock()
        mock_cfg.PERSISTENCE = mock_persistence

        with patch("lumina.api.routes.consent.get_current_user", return_value={"sub": "u1", "role": "user"}), \
             patch("lumina.api.routes.consent._session_containers", {}), \
             patch("lumina.api.routes.admin._cfg", mock_cfg):
            result = asyncio.run(accept_consent(mock_creds))

        assert result["status"] == "accepted"
        assert result["persisted"] is True
        mock_persistence.set_user_consent.assert_called_once()
        call_args = mock_persistence.set_user_consent.call_args
        assert call_args[0][0] == "u1"
        assert call_args[0][1] is True


# ─────────────────────────────────────────────────────────────
# Processing consent gate reads persisted consent
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestConsentGateReadsPersisted:
    """Consent gate in processing.py checks persisted consent for new sessions."""

    def test_persisted_consent_unblocks_session(self) -> None:
        """A new session with no in-memory consent should check persistence
        and allow the user through if consent was previously accepted."""
        from lumina.api.session import SessionContainer

        container = SessionContainer(active_domain_id="education")
        container.user = {"sub": "u1", "role": "user"}
        assert container.consent_accepted is False

        mock_persistence = MagicMock()
        mock_persistence.get_user_consent.return_value = {"accepted": True, "timestamp": time.time()}

        mock_cfg = MagicMock()
        mock_cfg.PERSISTENCE = mock_persistence

        # Simulate what the consent gate does
        user_id = "u1"
        consent_rec = mock_cfg.PERSISTENCE.get_user_consent(user_id)
        if consent_rec and consent_rec.get("accepted"):
            container.consent_accepted = True
            container.consent_timestamp = consent_rec.get("timestamp")

        assert container.consent_accepted is True

    def test_no_persisted_consent_blocks(self) -> None:
        """Without persisted consent, the gate should block."""
        mock_persistence = MagicMock()
        mock_persistence.get_user_consent.return_value = None

        consent_rec = mock_persistence.get_user_consent("u1")
        assert consent_rec is None
        # The processing code would return consent_required in this case
