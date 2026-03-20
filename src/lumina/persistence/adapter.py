from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from lumina.system_log.commit_guard import notify_log_commit


class PersistenceAdapter(ABC):
    """Domain-agnostic persistence interface for runtime and System Log operations."""

    @abstractmethod
    def load_domain_physics(self, path: str) -> dict[str, Any]:
        """Load domain physics document from persistent storage."""

    @abstractmethod
    def load_subject_profile(self, path: str) -> dict[str, Any]:
        """Load subject profile document from persistent storage."""

    @abstractmethod
    def save_subject_profile(self, path: str, data: dict[str, Any]) -> None:
        """Persist a subject profile document (atomic write)."""

    @abstractmethod
    def get_log_ledger_path(self, session_id: str, domain_id: str | None = None) -> str:
        """Return a stable ledger path for a given session.

        When *domain_id* is provided, the path is scoped to that domain
        context (e.g. ``session-{sid}-{domain_id}.jsonl``).  Use
        ``domain_id="_meta"`` for the session meta-ledger.
        """

    @abstractmethod
    def append_log_record(self, session_id: str, record: dict[str, Any], ledger_path: str | None = None) -> None:
        """Append one System Log record for the session."""

    @abstractmethod
    def load_session_state(self, session_id: str) -> dict[str, Any] | None:
        """Load persisted session metadata if present."""

    @abstractmethod
    def save_session_state(self, session_id: str, state: dict[str, Any]) -> None:
        """Persist session metadata."""

    @abstractmethod
    def list_log_session_ids(self) -> list[str]:
        """Return known System Log session IDs for the current backend."""

    @abstractmethod
    def validate_log_chain(self, session_id: str | None = None) -> dict[str, Any]:
        """Validate System Log hash-chain integrity for one session or all sessions."""

    @abstractmethod
    def has_policy_commitment(
        self,
        subject_id: str,
        subject_version: str | None,
        subject_hash: str,
    ) -> bool:
        """Return True when System Log contains a matching policy CommitmentRecord."""

    @abstractmethod
    def get_system_log_ledger_path(self) -> str:
        """Return the ledger path for the system-physics System Log."""

    @abstractmethod
    def has_system_physics_commitment(self, system_physics_hash: str) -> bool:
        """Return True when the system log contains a CommitmentRecord for this system-physics hash."""

    @abstractmethod
    def append_system_log_record(self, record: dict[str, Any]) -> None:
        """Append one record to the system-physics System Log."""

    # ── User / Auth persistence ──────────────────────────────

    @abstractmethod
    def create_user(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        role: str,
        governed_modules: list[str] | None = None,
        active: bool = True,
    ) -> dict[str, Any]:
        """Persist a new user record.  Returns the stored representation."""

    @abstractmethod
    def get_user(self, user_id: str) -> dict[str, Any] | None:
        """Return user record by ID, or None."""

    @abstractmethod
    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        """Return user record by username, or None."""

    @abstractmethod
    def list_users(self) -> list[dict[str, Any]]:
        """Return all user records (password hashes excluded)."""

    @abstractmethod
    def update_user_role(
        self,
        user_id: str,
        role: str,
        governed_modules: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Update role/governed_modules for an existing user. Returns updated record or None."""

    @abstractmethod
    def activate_user(self, user_id: str) -> bool:
        """Activate a pending user account. Returns True if found and activated."""

    @abstractmethod
    def deactivate_user(self, user_id: str) -> bool:
        """Soft-delete a user. Returns True if found and deactivated."""

    @abstractmethod
    def update_user_password(self, user_id: str, new_hash: str) -> bool:
        """Update stored password hash. Returns True if user found and updated."""

    @abstractmethod
    def update_user_domain_roles(
        self,
        user_id: str,
        domain_roles: dict[str, str],
    ) -> dict[str, Any] | None:
        """Merge domain_roles mapping into user record. Returns updated record (no password_hash) or None."""

    @abstractmethod
    def query_log_records(
        self,
        session_id: str | None = None,
        record_type: str | None = None,
        event_type: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query System Log records across all sessions with optional filters."""

    @abstractmethod
    def list_log_sessions_summary(self) -> list[dict[str, Any]]:
        """Return summary info for each System Log session."""

    @abstractmethod
    def query_escalations(
        self,
        status: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query EscalationRecords with optional filters."""

    @abstractmethod
    def query_commitments(self, subject_id: str) -> list[dict[str, Any]]:
        """Query CommitmentRecords for a given subject_id."""


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

    def save_subject_profile(self, path: str, data: dict[str, Any]) -> None:
        return None

    def get_log_ledger_path(self, session_id: str, domain_id: str | None = None) -> str:
        if domain_id:
            return f"session-{session_id}-{domain_id}.jsonl"
        return f"session-{session_id}.jsonl"

    def append_log_record(self, session_id: str, record: dict[str, Any], ledger_path: str | None = None) -> None:
        notify_log_commit()
        return None

    def load_session_state(self, session_id: str) -> dict[str, Any] | None:
        return dict(self._session_state[session_id]) if session_id in self._session_state else None

    def save_session_state(self, session_id: str, state: dict[str, Any]) -> None:
        self._session_state[session_id] = dict(state)

    def list_log_session_ids(self) -> list[str]:
        return []

    def validate_log_chain(self, session_id: str | None = None) -> dict[str, Any]:
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

    def has_policy_commitment(
        self,
        subject_id: str,
        subject_version: str | None,
        subject_hash: str,
    ) -> bool:
        return True

    def get_system_log_ledger_path(self) -> str:
        return "system/system.jsonl"

    def has_system_physics_commitment(self, system_physics_hash: str) -> bool:
        return True

    def append_system_log_record(self, record: dict[str, Any]) -> None:
        notify_log_commit()
        return None

    # ── User / Auth (in-memory) ──────────────────────────────

    def __init_users(self) -> None:
        if not hasattr(self, "_users"):
            self._users: dict[str, dict[str, Any]] = {}

    def create_user(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        role: str,
        governed_modules: list[str] | None = None,
        active: bool = True,
    ) -> dict[str, Any]:
        self.__init_users()
        record = {
            "user_id": user_id,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "governed_modules": governed_modules or [],
            "active": active,
        }
        self._users[user_id] = record
        return {k: v for k, v in record.items() if k != "password_hash"}

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        self.__init_users()
        return self._users.get(user_id)

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        self.__init_users()
        for u in self._users.values():
            if u["username"] == username:
                return u
        return None

    def list_users(self) -> list[dict[str, Any]]:
        self.__init_users()
        return [
            {k: v for k, v in u.items() if k != "password_hash"}
            for u in self._users.values()
        ]

    def update_user_role(
        self,
        user_id: str,
        role: str,
        governed_modules: list[str] | None = None,
    ) -> dict[str, Any] | None:
        self.__init_users()
        if user_id not in self._users:
            return None
        self._users[user_id]["role"] = role
        if governed_modules is not None:
            self._users[user_id]["governed_modules"] = governed_modules
        return {k: v for k, v in self._users[user_id].items() if k != "password_hash"}

    def activate_user(self, user_id: str) -> bool:
        self.__init_users()
        if user_id not in self._users:
            return False
        self._users[user_id]["active"] = True
        return True

    def deactivate_user(self, user_id: str) -> bool:
        self.__init_users()
        if user_id not in self._users:
            return False
        self._users[user_id]["active"] = False
        return True

    def update_user_password(self, user_id: str, new_hash: str) -> bool:
        self.__init_users()
        if user_id not in self._users:
            return False
        self._users[user_id]["password_hash"] = new_hash
        return True

    def update_user_domain_roles(self, user_id: str, domain_roles: dict[str, str]) -> dict[str, Any] | None:
        self.__init_users()
        if user_id not in self._users:
            return None
        existing = dict(self._users[user_id].get("domain_roles") or {})
        existing.update(domain_roles)
        self._users[user_id]["domain_roles"] = existing
        return {k: v for k, v in self._users[user_id].items() if k != "password_hash"}

    def query_log_records(
        self,
        session_id: str | None = None,
        record_type: str | None = None,
        event_type: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return []

    def list_log_sessions_summary(self) -> list[dict[str, Any]]:
        return []

    def query_escalations(
        self,
        status: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return []

    def query_commitments(self, subject_id: str) -> list[dict[str, Any]]:
        return []
