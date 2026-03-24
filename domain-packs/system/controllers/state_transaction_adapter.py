"""state_transaction_adapter.py — Tool adapter for state transaction queries.

Exposes ``state_transaction_info`` and ``state_transaction_advance``
as system-domain tool adapters.  These are registered under
``adapters.tools`` in the system domain's runtime-config.yaml and
invoked via the command-dispatch layer.

Like all tool adapters, this module is self-contained — it imports only
from ``lumina.core.state_machine`` (which has no server dependencies).
"""
from __future__ import annotations

from typing import Any

from lumina.core.state_machine import (
    IllegalTransitionError,
    StateTransaction,
    TransactionState,
)


def state_transaction_info(payload: dict[str, Any]) -> dict[str, Any]:
    """Return metadata about a state transaction.

    Expected payload::

        {"transaction": { ... serialized StateTransaction dict ... }}

    Returns the transaction's current state, legal next targets,
    whether it is terminal, and its full history.
    """
    txn_raw = payload.get("transaction")
    if not isinstance(txn_raw, dict) or "transaction_id" not in txn_raw:
        return {"error": "Missing or invalid 'transaction' dict in payload"}

    txn = StateTransaction.from_dict(txn_raw)
    return {
        "transaction_id": txn.transaction_id,
        "operation": txn.operation,
        "state": txn.state.value,
        "is_terminal": txn.is_terminal,
        "legal_targets": sorted(s.value for s in txn.legal_targets),
        "history": [
            {"state": s, "actor_id": a, "timestamp": t}
            for s, a, t in txn.history
        ],
    }


def state_transaction_advance(payload: dict[str, Any]) -> dict[str, Any]:
    """Advance a state transaction to a new state.

    Expected payload::

        {
            "transaction": { ... serialized StateTransaction dict ... },
            "target_state": "COMMITTED",
            "actor_id": "root"
        }

    Returns the updated transaction dict on success, or an error dict
    if the transition is illegal.
    """
    txn_raw = payload.get("transaction")
    if not isinstance(txn_raw, dict) or "transaction_id" not in txn_raw:
        return {"error": "Missing or invalid 'transaction' dict in payload"}

    target_name = payload.get("target_state", "")
    try:
        target = TransactionState(target_name)
    except ValueError:
        return {
            "error": f"Unknown target state: {target_name!r}",
            "valid_states": [s.value for s in TransactionState],
        }

    actor_id = payload.get("actor_id", "")
    metadata_update = payload.get("metadata_update")

    txn = StateTransaction.from_dict(txn_raw)
    try:
        txn = txn.advance(target, actor_id=actor_id or None, metadata_update=metadata_update)
    except IllegalTransitionError as exc:
        return {
            "error": str(exc),
            "current_state": exc.current.value,
            "target_state": exc.target.value,
        }

    return {"transaction": txn.to_dict()}
