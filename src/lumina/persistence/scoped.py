"""Scoped persistence wrapper enforcing HMVC ledger tier isolation.

Domain-pack operation handlers receive a ``ScopedPersistenceAdapter``
instead of the raw persistence adapter.  Writes are automatically routed
to the correct tier ledger; system-tier writes are blocked.

See docs/7-concepts/ledger-tier-separation.md
"""

from __future__ import annotations

from typing import Any


class ScopedPersistenceAdapter:
    """Thin wrapper that routes log writes to the correct tier.

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

    # ── Delegate everything else unchanged ───────────────────

    def __getattr__(self, name: str) -> Any:
        """Proxy non-log methods (profiles, users, etc.) to inner adapter."""
        return getattr(self._inner, name)
