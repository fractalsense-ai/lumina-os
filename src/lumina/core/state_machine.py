"""Atomic State Machine — the 4-stage ACK.

Provides a single, reusable state-transition kernel for all
transactional workflows in Lumina: admin HITL commands, staged-file
approvals, domain-physics updates, and future operations.

States
------
PROPOSED   – intent declared, not yet validated
VALIDATED  – schema/policy checks passed
COMMITTED  – accepted by an authority, executing side-effects
FINALIZED  – all side-effects persisted, immutable
ROLLED_BACK – aborted after PROPOSED or VALIDATED (never after COMMITTED)

Legal transitions::

    PROPOSED   → VALIDATED | ROLLED_BACK
    VALIDATED  → COMMITTED | ROLLED_BACK
    COMMITTED  → FINALIZED
    FINALIZED  → (terminal)
    ROLLED_BACK → (terminal)

Design invariants:
* Once COMMITTED, a transaction **cannot** be rolled back — only forward
  to FINALIZED.  Undo is a *new* compensating transaction.
* Every ``advance()`` returns a *new* ``StateTransaction`` (immutable
  transitions).  The caller persists it.
* ``metadata`` is an open dict for domain-specific context; the kernel
  never inspects it.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


# ------------------------------------------------------------------
# Enum
# ------------------------------------------------------------------

class TransactionState(enum.Enum):
    """Legal states for a ``StateTransaction``."""

    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    COMMITTED = "COMMITTED"
    FINALIZED = "FINALIZED"
    ROLLED_BACK = "ROLLED_BACK"


# ------------------------------------------------------------------
# Transition table
# ------------------------------------------------------------------

_LEGAL_TRANSITIONS: dict[TransactionState, frozenset[TransactionState]] = {
    TransactionState.PROPOSED: frozenset({TransactionState.VALIDATED, TransactionState.ROLLED_BACK}),
    TransactionState.VALIDATED: frozenset({TransactionState.COMMITTED, TransactionState.ROLLED_BACK}),
    TransactionState.COMMITTED: frozenset({TransactionState.FINALIZED}),
    TransactionState.FINALIZED: frozenset(),
    TransactionState.ROLLED_BACK: frozenset(),
}


# ------------------------------------------------------------------
# Errors
# ------------------------------------------------------------------

class IllegalTransitionError(Exception):
    """Raised when ``advance()`` is called with an invalid target state."""

    def __init__(self, current: TransactionState, target: TransactionState) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Illegal transition: {current.value} → {target.value}. "
            f"Legal targets: {sorted(s.value for s in _LEGAL_TRANSITIONS[current])}"
        )


# ------------------------------------------------------------------
# Transaction
# ------------------------------------------------------------------

@dataclass(frozen=True)
class StateTransaction:
    """Immutable snapshot of a transactional workflow step.

    Parameters
    ----------
    transaction_id:
        Globally unique ID (auto-generated when omitted).
    operation:
        Logical operation name (e.g. ``"invite_user"``, ``"stage_file"``).
    state:
        Current :class:`TransactionState`.
    actor_id:
        ID of the actor who initiated *or* is advancing this step.
    created_at:
        Unix timestamp of the original PROPOSED creation.
    updated_at:
        Unix timestamp of the most recent ``advance()``.
    metadata:
        Open dict — caller stores domain-specific context here.
    history:
        Ordered list of ``(state_value, actor_id, timestamp)`` tuples
        recording every transition.
    """

    transaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    operation: str = ""
    state: TransactionState = TransactionState.PROPOSED
    actor_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    history: tuple[tuple[str, str, float], ...] = ()

    # -- Query helpers ------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        """``True`` when no further transitions are legal."""
        return not _LEGAL_TRANSITIONS[self.state]

    @property
    def legal_targets(self) -> frozenset[TransactionState]:
        """Return the set of states reachable from the current state."""
        return _LEGAL_TRANSITIONS[self.state]

    def can_advance(self, target: TransactionState) -> bool:
        """Check whether *target* is a legal next state."""
        return target in _LEGAL_TRANSITIONS[self.state]

    # -- Transition ---------------------------------------------------

    def advance(
        self,
        target: TransactionState,
        actor_id: str | None = None,
        metadata_update: dict[str, Any] | None = None,
    ) -> StateTransaction:
        """Return a **new** ``StateTransaction`` in *target* state.

        Parameters
        ----------
        target:
            The desired next state.
        actor_id:
            Actor performing this transition.  Falls back to the
            original ``self.actor_id`` if omitted.
        metadata_update:
            Keys to *merge* into the existing metadata dict.

        Raises
        ------
        IllegalTransitionError
            When *target* is not reachable from the current state.
        """
        if not self.can_advance(target):
            raise IllegalTransitionError(self.state, target)

        now = time.time()
        new_actor = actor_id or self.actor_id
        new_meta = {**self.metadata, **(metadata_update or {})}
        new_history = self.history + ((target.value, new_actor, now),)

        return StateTransaction(
            transaction_id=self.transaction_id,
            operation=self.operation,
            state=target,
            actor_id=new_actor,
            created_at=self.created_at,
            updated_at=now,
            metadata=new_meta,
            history=new_history,
        )

    # -- Serialization ------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Produce a JSON-safe dictionary."""
        d = asdict(self)
        d["state"] = self.state.value
        d["history"] = [
            {"state": s, "actor_id": a, "timestamp": t}
            for s, a, t in self.history
        ]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateTransaction:
        """Reconstruct a ``StateTransaction`` from a dict (e.g. JSON)."""
        history_raw = data.get("history", [])
        history: tuple[tuple[str, str, float], ...] = tuple(
            (h["state"], h["actor_id"], h["timestamp"])
            for h in history_raw
        )
        return cls(
            transaction_id=data["transaction_id"],
            operation=data.get("operation", ""),
            state=TransactionState(data["state"]),
            actor_id=data.get("actor_id", ""),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
            metadata=data.get("metadata", {}),
            history=history,
        )
