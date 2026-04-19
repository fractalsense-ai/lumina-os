from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from lumina.system_log.commit_guard import notify_log_commit


# ─────────────────────────────────────────────────────────────
# HMVC Persistence ABC Hierarchy
#
# The persistence interface is split into three tiers so that the
# ScopedPersistenceAdapter can enforce domain-pack isolation at the
# type level:
#
#   SystemPersistence  – user/auth/consent/system-log (system-only)
#   DomainPersistence  – profiles/module-state/domain-physics/logs
#   PersistenceAdapter – combines both + shared cross-cutting methods
# ─────────────────────────────────────────────────────────────


class SystemPersistence(ABC):
    """Persistence methods reserved for the system layer.

    Domain-pack handlers must NEVER receive a reference to this
    interface directly.  The ``ScopedPersistenceAdapter`` blocks
    these methods at runtime.
    """

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
    def set_user_invite_token(self, user_id: str, token: str, expires_at: float) -> bool:
        """Persist an invite token for a pending user.  Returns True if stored."""

    @abstractmethod
    def get_user_by_invite_token(self, token: str) -> dict[str, Any] | None:
        """Return user record for a matching, non-expired invite token, or None."""

    @abstractmethod
    def clear_user_invite_token(self, user_id: str) -> bool:
        """Remove the invite token from a user record.  Returns True if found."""

    @abstractmethod
    def update_user_domain_roles(
        self,
        user_id: str,
        domain_roles: dict[str, str],
    ) -> dict[str, Any] | None:
        """Merge domain_roles mapping into user record. Returns updated record (no password_hash) or None."""

    @abstractmethod
    def update_user_governed_modules(
        self,
        user_id: str,
        *,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Atomically add/remove module IDs from a user's governed_modules list.

        Returns the updated user record (no password_hash) or None if user not found.
        Duplicate additions are ignored (idempotent).
        """

    # ── User-level consent persistence ────────────────────────

    @abstractmethod
    def set_user_consent(self, user_id: str, accepted: bool, timestamp: float) -> bool:
        """Persist consent acceptance for a user. Returns True on success."""

    @abstractmethod
    def get_user_consent(self, user_id: str) -> dict[str, Any] | None:
        """Return ``{accepted: bool, timestamp: float}`` or None if no record."""

    # ── System-tier log operations ────────────────────────────

    @abstractmethod
    def get_system_ledger_path(self, session_id: str) -> str:
        """Return the ledger path for a system-tier log (auth, session, routing).

        Layout: ``system/session-{sid}.jsonl``
        """

    @abstractmethod
    def get_system_log_ledger_path(self) -> str:
        """Return the ledger path for the system-physics System Log."""

    @abstractmethod
    def has_system_physics_commitment(self, system_physics_hash: str) -> bool:
        """Return True when the system log contains a CommitmentRecord for this system-physics hash."""

    @abstractmethod
    def append_system_log_record(self, record: dict[str, Any]) -> None:
        """Append one record to the system-physics System Log."""


class DomainPersistence(ABC):
    """Persistence methods available to domain-pack handlers.

    The ``ScopedPersistenceAdapter`` delegates these methods with
    automatic domain_id scoping where applicable.
    """

    # ── Domain physics ───────────────────────────────────────

    @abstractmethod
    def load_domain_physics(self, path: str) -> dict[str, Any]:
        """Load domain physics document from persistent storage."""

    # ── Path-based profile persistence (deprecated) ──────────

    @abstractmethod
    def load_subject_profile(self, path: str) -> dict[str, Any]:
        """Load subject profile document from persistent storage.

        .. deprecated:: Use :meth:`load_profile` instead.
        """

    @abstractmethod
    def save_subject_profile(self, path: str, data: dict[str, Any]) -> None:
        """Persist a subject profile document (atomic write).

        .. deprecated:: Use :meth:`save_profile` instead.
        """

    # ── Key-based profile persistence ────────────────────────

    @abstractmethod
    def load_profile(self, user_id: str, domain_key: str) -> dict[str, Any] | None:
        """Load a user profile by composite key. Returns None if not found."""

    @abstractmethod
    def save_profile(self, user_id: str, domain_key: str, data: dict[str, Any]) -> None:
        """Persist a user profile by composite key (upsert)."""

    @abstractmethod
    def list_profiles(self, user_id: str) -> list[str]:
        """Return domain_key values for which profiles exist for this user."""

    @abstractmethod
    def delete_profile(self, user_id: str, domain_key: str) -> bool:
        """Delete a profile. Returns True if it existed."""

    # ── Domain / module tier log paths ───────────────────────

    @abstractmethod
    def get_domain_ledger_path(self, domain_id: str) -> str:
        """Return the ledger path for a domain-tier log (RBAC, escalations, commits).

        Layout: ``domains/{domain}/domain.jsonl``
        """

    @abstractmethod
    def get_module_ledger_path(self, domain_id: str, module_id: str) -> str:
        """Return the ledger path for a module-tier log (student ops, assignments).

        Layout: ``domains/{domain}/modules/{module_id}.jsonl``
        """

    # ── Module state persistence ─────────────────────────────

    @abstractmethod
    def load_module_state(self, user_id: str, module_key: str) -> dict[str, Any] | None:
        """Load opaque per-actor per-module state blob, or None if not found."""

    @abstractmethod
    def save_module_state(self, user_id: str, module_key: str, state: dict[str, Any]) -> None:
        """Persist opaque per-actor per-module state blob (upsert)."""

    @abstractmethod
    def list_module_states(self, user_id: str) -> list[str]:
        """Return module_key values for which state exists for this user."""

    @abstractmethod
    def delete_module_state(self, user_id: str, module_key: str) -> bool:
        """Delete a module state entry. Returns True if it existed."""


class PersistenceAdapter(SystemPersistence, DomainPersistence):
    """Full persistence interface combining system and domain tiers.

    Concrete adapters (Filesystem, SQLite) implement this.  The global
    ``PERSISTENCE`` singleton in ``config.py`` is typed as this.

    Domain-pack handlers should receive a ``ScopedPersistenceAdapter``
    instead, which enforces HMVC isolation by blocking system methods
    and scoping domain methods to the handler's domain_id.
    """

    # ── Shared / cross-cutting methods ───────────────────────
    # These span both tiers and are available to all callers.

    @abstractmethod
    def get_log_ledger_path(self, session_id: str, domain_id: str | None = None) -> str:
        """Return a stable ledger path for a given session.

        When *domain_id* is provided, the path is scoped to that domain
        context (e.g. ``session-{sid}-{domain_id}.jsonl``).  Use
        ``domain_id="_meta"`` for the session meta-ledger.

        .. deprecated:: Use the tier-specific methods instead.
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
        self._profiles: dict[str, dict[str, dict[str, Any]]] = {}  # user_id → domain_key → data

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

    # ── Key-based profile (in-memory) ─────────────────────────

    def load_profile(self, user_id: str, domain_key: str) -> dict[str, Any] | None:
        return self._profiles.get(user_id, {}).get(domain_key)

    def save_profile(self, user_id: str, domain_key: str, data: dict[str, Any]) -> None:
        self._profiles.setdefault(user_id, {})[domain_key] = dict(data)

    def list_profiles(self, user_id: str) -> list[str]:
        return list(self._profiles.get(user_id, {}).keys())

    def delete_profile(self, user_id: str, domain_key: str) -> bool:
        bucket = self._profiles.get(user_id, {})
        if domain_key in bucket:
            del bucket[domain_key]
            return True
        return False

    def get_log_ledger_path(self, session_id: str, domain_id: str | None = None) -> str:
        if domain_id:
            return f"session-{session_id}-{domain_id}.jsonl"
        return f"session-{session_id}.jsonl"

    def get_system_ledger_path(self, session_id: str) -> str:
        return f"system/session-{session_id}.jsonl"

    def get_domain_ledger_path(self, domain_id: str) -> str:
        return f"domains/{domain_id}/domain.jsonl"

    def get_module_ledger_path(self, domain_id: str, module_id: str) -> str:
        return f"domains/{domain_id}/modules/{module_id}.jsonl"

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

    def update_user_governed_modules(
        self,
        user_id: str,
        *,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict[str, Any] | None:
        self.__init_users()
        if user_id not in self._users:
            return None
        modules = list(self._users[user_id].get("governed_modules") or [])
        for m in (add or []):
            if m not in modules:
                modules.append(m)
        for m in (remove or []):
            if m in modules:
                modules.remove(m)
        self._users[user_id]["governed_modules"] = modules
        return {k: v for k, v in self._users[user_id].items() if k != "password_hash"}

    def set_user_invite_token(self, user_id: str, token: str, expires_at: float) -> bool:
        self.__init_users()
        if user_id not in self._users:
            return False
        self._users[user_id]["invite_token"] = token
        self._users[user_id]["invite_token_expires_at"] = expires_at
        return True

    def get_user_by_invite_token(self, token: str) -> dict[str, Any] | None:
        import time as _time
        self.__init_users()
        now = _time.time()
        for u in self._users.values():
            if u.get("invite_token") == token and u.get("invite_token_expires_at", 0) > now:
                return {k: v for k, v in u.items() if k != "password_hash"}
        return None

    def clear_user_invite_token(self, user_id: str) -> bool:
        self.__init_users()
        if user_id not in self._users:
            return False
        self._users[user_id].pop("invite_token", None)
        self._users[user_id].pop("invite_token_expires_at", None)
        return True

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

    def set_user_consent(self, user_id: str, accepted: bool, timestamp: float) -> bool:
        self.__init_users()
        if user_id not in self._users:
            return False
        self._users[user_id]["consent_accepted"] = accepted
        self._users[user_id]["consent_timestamp"] = timestamp
        return True

    def get_user_consent(self, user_id: str) -> dict[str, Any] | None:
        self.__init_users()
        u = self._users.get(user_id)
        if u is None:
            return None
        if "consent_accepted" not in u:
            return None
        return {"accepted": u["consent_accepted"], "timestamp": u.get("consent_timestamp")}

    # ── Module state (in-memory) ──────────────────────────────

    def __init_module_states(self) -> None:
        if not hasattr(self, "_module_states"):
            self._module_states: dict[str, dict[str, dict[str, Any]]] = {}

    def load_module_state(self, user_id: str, module_key: str) -> dict[str, Any] | None:
        self.__init_module_states()
        return self._module_states.get(user_id, {}).get(module_key)

    def save_module_state(self, user_id: str, module_key: str, state: dict[str, Any]) -> None:
        self.__init_module_states()
        self._module_states.setdefault(user_id, {})[module_key] = dict(state)

    def list_module_states(self, user_id: str) -> list[str]:
        self.__init_module_states()
        return list(self._module_states.get(user_id, {}).keys())

    def delete_module_state(self, user_id: str, module_key: str) -> bool:
        self.__init_module_states()
        bucket = self._module_states.get(user_id, {})
        if module_key in bucket:
            del bucket[module_key]
            return True
        return False
