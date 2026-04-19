"""Scoped persistence wrapper enforcing HMVC domain-pack isolation.

Domain-pack operation handlers receive a ``ScopedPersistenceAdapter``
instead of the raw persistence adapter.  This wrapper:

1. **Blocks** system-tier methods (user CRUD, consent, system logs)
2. **Scopes** domain methods to the handler's domain_id
3. **Routes** log writes to the correct tier ledger

See docs/7-concepts/ledger-tier-separation.md
"""

from __future__ import annotations

from typing import Any


# ── System methods that domain-pack handlers cannot call ─────
# These are all defined on SystemPersistence and must be blocked
# when accessed through a scoped adapter.

_BLOCKED_SYSTEM_METHODS: frozenset[str] = frozenset({
    # User mutation
    "create_user",
    "update_user_role",
    "activate_user",
    "deactivate_user",
    "update_user_password",
    "set_user_invite_token",
    "clear_user_invite_token",
    "list_users",
    # Consent mutation
    "set_user_consent",
    # System-tier log operations
    "append_system_log_record",
    "get_system_log_ledger_path",
    "has_system_physics_commitment",
    "get_system_ledger_path",
})


def _strip_password_hash(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a copy of a user record with password_hash removed."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if k != "password_hash"}


class ScopedPersistenceAdapter:
    """HMVC-enforcing wrapper that isolates domain-pack handlers.

    Parameters
    ----------
    inner:
        The underlying ``PersistenceAdapter`` (filesystem or sqlite).
    domain_id:
        The domain this adapter is scoped to (e.g. ``"education"``).
    module_id:
        Optional module ID for module-tier scoping.
    """

    def __init__(
        self,
        inner: Any,
        domain_id: str,
        module_id: str | None = None,
    ) -> None:
        self._inner = inner
        self.domain_id = domain_id
        self.module_id = module_id

    # ── Tier-routed log writes ───────────────────────────────

    def append_log_record(
        self,
        session_id: str,
        record: dict[str, Any],
        ledger_path: str | None = None,
    ) -> None:
        """Append a record to the domain-tier ledger.

        If *ledger_path* is explicitly provided it is honoured (for
        backward compat).  Otherwise the record is written to the
        domain ledger for this adapter's ``domain_id``.
        """
        if ledger_path is None:
            ledger_path = self._inner.get_domain_ledger_path(self.domain_id)
        self._inner.append_log_record(session_id, record, ledger_path=ledger_path)

    def append_domain_log_record(
        self,
        session_id: str,
        record: dict[str, Any],
    ) -> None:
        """Write to the domain-tier ledger for this adapter's domain."""
        path = self._inner.get_domain_ledger_path(self.domain_id)
        self._inner.append_log_record(session_id, record, ledger_path=path)

    def append_module_log_record(
        self,
        session_id: str,
        record: dict[str, Any],
        module_id: str | None = None,
    ) -> None:
        """Write to a module-tier ledger under this adapter's domain."""
        mid = module_id or self.module_id
        if mid is None:
            raise ValueError("module_id required for module-tier log write")
        path = self._inner.get_module_ledger_path(self.domain_id, mid)
        self._inner.append_log_record(session_id, record, ledger_path=path)

    # ── Blocked system-tier writes ───────────────────────────

    def append_system_log_record(self, record: dict[str, Any]) -> None:
        """Domain handlers cannot write to the system-tier ledger."""
        raise PermissionError(
            f"ScopedPersistenceAdapter(domain={self.domain_id!r}) "
            "cannot write to the system-tier ledger"
        )

    # ── Tier path accessors ──────────────────────────────────

    def get_domain_ledger_path(self, domain_id: str | None = None) -> str:
        return self._inner.get_domain_ledger_path(domain_id or self.domain_id)

    def get_module_ledger_path(self, domain_id: str | None = None, module_id: str | None = None) -> str:
        return self._inner.get_module_ledger_path(
            domain_id or self.domain_id,
            module_id or self.module_id or "",
        )

    def get_log_ledger_path(self, session_id: str, domain_id: str | None = None) -> str:
        """Backward compat — delegates to inner."""
        return self._inner.get_log_ledger_path(session_id, domain_id=domain_id)

    # ── Query — scoped to this domain by default ─────────────

    def query_log_records(self, **kwargs: Any) -> list[dict[str, Any]]:
        kwargs.setdefault("domain_id", self.domain_id)
        return self._inner.query_log_records(**kwargs)

    # ── Safe user reads (password_hash stripped) ─────────────
    # Domain-pack handlers may need to resolve user info for
    # operations like "assign teacher to module".  Read access is
    # allowed but password hashes are always stripped.

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return _strip_password_hash(self._inner.get_user(user_id))

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        return _strip_password_hash(self._inner.get_user_by_username(username))

    def get_user_consent(self, user_id: str) -> dict[str, Any] | None:
        return self._inner.get_user_consent(user_id)

    # ── Scoped user mutations ────────────────────────────────
    # Domain packs may manage governed_modules and domain_roles,
    # but only for modules/roles belonging to their own domain.

    def _is_in_scope(self, module_or_key: str) -> bool:
        """Return True if the identifier belongs to this domain.

        Accepts:
        - The domain_id itself (``"education"``)
        - Hierarchical IDs prefixed with the domain_id (``"education/algebra-v1"``)
        - Simple names without ``/`` (implicitly belong to the current domain)

        Rejects hierarchical IDs that start with a *different* domain prefix.
        """
        if module_or_key == self.domain_id:
            return True
        if module_or_key.startswith(self.domain_id + "/"):
            return True
        # Simple (non-hierarchical) names are considered in-scope
        if "/" not in module_or_key:
            return True
        return False

    def update_user_governed_modules(
        self,
        user_id: str,
        *,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Update governed_modules, scoped to this domain's modules only."""
        if add:
            for m in add:
                if not self._is_in_scope(m):
                    raise PermissionError(
                        f"ScopedPersistenceAdapter(domain={self.domain_id!r}) "
                        f"cannot add governed module {m!r} — not in domain scope"
                    )
        if remove:
            for m in remove:
                if not self._is_in_scope(m):
                    raise PermissionError(
                        f"ScopedPersistenceAdapter(domain={self.domain_id!r}) "
                        f"cannot remove governed module {m!r} — not in domain scope"
                    )
        kwargs: dict[str, list[str]] = {}
        if add is not None:
            kwargs["add"] = add
        if remove is not None:
            kwargs["remove"] = remove
        return self._inner.update_user_governed_modules(user_id, **kwargs)

    def update_user_domain_roles(
        self,
        user_id: str,
        domain_roles: dict[str, str],
    ) -> dict[str, Any] | None:
        """Update domain_roles, scoped to this domain only."""
        for key in domain_roles:
            if not self._is_in_scope(key):
                raise PermissionError(
                    f"ScopedPersistenceAdapter(domain={self.domain_id!r}) "
                    f"cannot set domain role for {key!r} — not in domain scope"
                )
        return self._inner.update_user_domain_roles(user_id, domain_roles)

    # ── Domain persistence methods (delegated) ───────────────

    def load_domain_physics(self, path: str) -> dict[str, Any]:
        return self._inner.load_domain_physics(path)

    def load_subject_profile(self, path: str) -> dict[str, Any]:
        return self._inner.load_subject_profile(path)

    def save_subject_profile(self, path: str, data: dict[str, Any]) -> None:
        return self._inner.save_subject_profile(path, data)

    def load_profile(self, user_id: str, domain_key: str) -> dict[str, Any] | None:
        return self._inner.load_profile(user_id, domain_key)

    def save_profile(self, user_id: str, domain_key: str, data: dict[str, Any]) -> None:
        return self._inner.save_profile(user_id, domain_key, data)

    def list_profiles(self, user_id: str) -> list[str]:
        return self._inner.list_profiles(user_id)

    def delete_profile(self, user_id: str, domain_key: str) -> bool:
        return self._inner.delete_profile(user_id, domain_key)

    def load_module_state(self, user_id: str, module_key: str) -> dict[str, Any] | None:
        return self._inner.load_module_state(user_id, module_key)

    def save_module_state(self, user_id: str, module_key: str, state: dict[str, Any]) -> None:
        return self._inner.save_module_state(user_id, module_key, state)

    def list_module_states(self, user_id: str) -> list[str]:
        return self._inner.list_module_states(user_id)

    def delete_module_state(self, user_id: str, module_key: str) -> bool:
        return self._inner.delete_module_state(user_id, module_key)

    # ── Shared / cross-cutting (delegated) ───────────────────

    def load_session_state(self, session_id: str) -> dict[str, Any] | None:
        return self._inner.load_session_state(session_id)

    def save_session_state(self, session_id: str, state: dict[str, Any]) -> None:
        return self._inner.save_session_state(session_id, state)

    def list_log_session_ids(self) -> list[str]:
        return self._inner.list_log_session_ids()

    def validate_log_chain(self, session_id: str | None = None) -> dict[str, Any]:
        return self._inner.validate_log_chain(session_id)

    def has_policy_commitment(
        self,
        subject_id: str,
        subject_version: str | None,
        subject_hash: str,
    ) -> bool:
        return self._inner.has_policy_commitment(subject_id, subject_version, subject_hash)

    def list_log_sessions_summary(self) -> list[dict[str, Any]]:
        return self._inner.list_log_sessions_summary()

    def query_escalations(self, **kwargs: Any) -> list[dict[str, Any]]:
        kwargs.setdefault("domain_id", self.domain_id)
        return self._inner.query_escalations(**kwargs)

    def query_commitments(self, subject_id: str) -> list[dict[str, Any]]:
        return self._inner.query_commitments(subject_id)

    # ── Catch-all: block unrecognised attribute access ───────

    def __getattr__(self, name: str) -> Any:
        """Block any method not explicitly delegated above.

        Previous versions proxied everything to the inner adapter,
        which allowed domain-pack handlers to bypass HMVC isolation
        and call system-level methods like ``create_user()``.
        """
        if name in _BLOCKED_SYSTEM_METHODS:
            raise PermissionError(
                f"ScopedPersistenceAdapter(domain={self.domain_id!r}) "
                f"cannot call system method {name!r}"
            )
        # For genuinely unknown attributes, raise the standard error
        raise AttributeError(
            f"ScopedPersistenceAdapter(domain={self.domain_id!r}) "
            f"does not expose {name!r} — check HMVC method allow-list"
        )
