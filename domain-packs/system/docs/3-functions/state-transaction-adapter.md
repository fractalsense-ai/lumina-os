# state-transaction-adapter(3)

## NAME

`state_transaction_adapter.py` — Tool adapter for querying and advancing state transactions

## SYNOPSIS

```python
from state_transaction_adapter import state_transaction_info, state_transaction_advance

info = state_transaction_info({"transaction": txn})
result = state_transaction_advance({"transaction": txn, "target_state": "COMMITTED", "actor_id": "root"})
```

## DESCRIPTION

`state_transaction_adapter.py` exposes the core state machine as a tool-adapter callable for
the system domain. It provides two functions:

- **`state_transaction_info(payload)`** — Returns the current state, whether it is terminal,
  legal target states, and the full transition history of a `StateTransaction` object.
- **`state_transaction_advance(payload)`** — Validates and advances a transaction to the
  requested target state. Returns the updated transaction dict on success, or an error dict
  with `"error"` and `"legal_targets"` on illegal transitions.

These adapters allow the orchestrator's policy system to inspect and drive transaction
lifecycles through YAML-declared tool-adapter bindings.

## SEE ALSO

[`state-change-commit-policy(7)`](../../../../docs/7-concepts/state-change-commit-policy.md),
[`command-execution-pipeline(7)`](../../../../docs/7-concepts/command-execution-pipeline.md),
[`domain-pack-anatomy(7)`](../../../../docs/7-concepts/domain-pack-anatomy.md)
