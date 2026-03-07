from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PersistenceAdapter(ABC):
    """Domain-agnostic persistence interface for runtime and CTL operations."""

    @abstractmethod
    def load_domain_physics(self, path: str) -> dict[str, Any]:
        """Load domain physics document from persistent storage."""

    @abstractmethod
    def load_subject_profile(self, path: str) -> dict[str, Any]:
        """Load subject profile document from persistent storage."""

    @abstractmethod
    def get_ctl_ledger_path(self, session_id: str) -> str:
        """Return a stable ledger path for a given session (used by file backends)."""

    @abstractmethod
    def append_ctl_record(self, session_id: str, record: dict[str, Any], ledger_path: str | None = None) -> None:
        """Append one CTL record for the session."""

    @abstractmethod
    def load_session_state(self, session_id: str) -> dict[str, Any] | None:
        """Load persisted session metadata if present."""

    @abstractmethod
    def save_session_state(self, session_id: str, state: dict[str, Any]) -> None:
        """Persist session metadata."""

    @abstractmethod
    def list_ctl_session_ids(self) -> list[str]:
        """Return known CTL session IDs for the current backend."""

    @abstractmethod
    def validate_ctl_chain(self, session_id: str | None = None) -> dict[str, Any]:
        """Validate CTL hash-chain integrity for one session or all sessions."""


class NullPersistenceAdapter(PersistenceAdapter):
    """No-op adapter mainly used for tests; keeps session state in-memory only."""

    def __init__(self) -> None:
        self._session_state: dict[str, dict[str, Any]] = {}

    def load_domain_physics(self, path: str) -> dict[str, Any]:
        import json

        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def load_subject_profile(self, path: str) -> dict[str, Any]:
        import importlib.util
        import sys
        from pathlib import Path

        p = Path(path)
        loader_path = p.parent.parent.parent / "reference-implementations" / "yaml-loader.py"
        spec = importlib.util.spec_from_file_location("persistence_yaml_loader", str(loader_path))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules["persistence_yaml_loader"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod.load_yaml(path)

    def get_ctl_ledger_path(self, session_id: str) -> str:
        return f"session-{session_id}.jsonl"

    def append_ctl_record(self, session_id: str, record: dict[str, Any], ledger_path: str | None = None) -> None:
        return None

    def load_session_state(self, session_id: str) -> dict[str, Any] | None:
        return dict(self._session_state[session_id]) if session_id in self._session_state else None

    def save_session_state(self, session_id: str, state: dict[str, Any]) -> None:
        self._session_state[session_id] = dict(state)

    def list_ctl_session_ids(self) -> list[str]:
        return []

    def validate_ctl_chain(self, session_id: str | None = None) -> dict[str, Any]:
        if session_id:
            return {
                "scope": "session",
                "session_id": session_id,
                "intact": True,
                "records_checked": 0,
                "error": None,
            }
        return {
            "scope": "all",
            "sessions_checked": 0,
            "intact": True,
            "results": [],
        }
