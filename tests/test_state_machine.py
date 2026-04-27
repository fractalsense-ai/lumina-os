"""Tests for lumina.core.state_machine — atomic state transaction kernel."""
from __future__ import annotations

import time

import pytest

from lumina.core.state_machine import (
    IllegalTransitionError,
    StateTransaction,
    TransactionState,
    _LEGAL_TRANSITIONS,
)


# ── Helpers ────────────────────────────────────────────────────

def _make_txn(**overrides) -> StateTransaction:
    defaults = dict(
        operation="test_op",
        actor_id="actor-1",
    )
    defaults.update(overrides)
    return StateTransaction(**defaults)


# ── TransactionState enum ─────────────────────────────────────


@pytest.mark.unit
class TestTransactionStateEnum:
    def test_all_states_present(self) -> None:
        names = {s.name for s in TransactionState}
        assert names == {"PROPOSED", "VALIDATED", "COMMITTED", "FINALIZED", "ROLLED_BACK"}

    def test_value_matches_name(self) -> None:
        for s in TransactionState:
            assert s.value == s.name

    def test_construct_from_value(self) -> None:
        assert TransactionState("PROPOSED") is TransactionState.PROPOSED


# ── Legal transitions ─────────────────────────────────────────


@pytest.mark.unit
class TestLegalTransitions:
    def test_proposed_targets(self) -> None:
        assert _LEGAL_TRANSITIONS[TransactionState.PROPOSED] == frozenset({
            TransactionState.VALIDATED, TransactionState.ROLLED_BACK,
        })

    def test_validated_targets(self) -> None:
        assert _LEGAL_TRANSITIONS[TransactionState.VALIDATED] == frozenset({
            TransactionState.COMMITTED, TransactionState.ROLLED_BACK,
        })

    def test_committed_targets(self) -> None:
        assert _LEGAL_TRANSITIONS[TransactionState.COMMITTED] == frozenset({
            TransactionState.FINALIZED,
        })

    def test_finalized_is_terminal(self) -> None:
        assert _LEGAL_TRANSITIONS[TransactionState.FINALIZED] == frozenset()

    def test_rolled_back_is_terminal(self) -> None:
        assert _LEGAL_TRANSITIONS[TransactionState.ROLLED_BACK] == frozenset()


# ── StateTransaction creation ─────────────────────────────────


@pytest.mark.unit
class TestStateTransactionCreation:
    def test_default_state_is_proposed(self) -> None:
        txn = _make_txn()
        assert txn.state is TransactionState.PROPOSED

    def test_transaction_id_is_uuid(self) -> None:
        txn = _make_txn()
        assert len(txn.transaction_id) == 36  # uuid4 format

    def test_auto_generated_id_is_unique(self) -> None:
        ids = {_make_txn().transaction_id for _ in range(100)}
        assert len(ids) == 100

    def test_timestamps_set(self) -> None:
        t0 = time.time()
        txn = _make_txn()
        assert txn.created_at >= t0
        assert txn.updated_at >= t0

    def test_empty_history(self) -> None:
        txn = _make_txn()
        assert txn.history == ()

    def test_metadata_default_empty(self) -> None:
        txn = _make_txn()
        assert txn.metadata == {}


# ── Query helpers ──────────────────────────────────────────────


@pytest.mark.unit
class TestQueryHelpers:
    def test_is_terminal_proposed(self) -> None:
        assert not _make_txn().is_terminal

    def test_is_terminal_finalized(self) -> None:
        txn = (_make_txn()
               .advance(TransactionState.VALIDATED)
               .advance(TransactionState.COMMITTED)
               .advance(TransactionState.FINALIZED))
        assert txn.is_terminal

    def test_is_terminal_rolled_back(self) -> None:
        txn = _make_txn().advance(TransactionState.ROLLED_BACK)
        assert txn.is_terminal

    def test_legal_targets_proposed(self) -> None:
        txn = _make_txn()
        assert txn.legal_targets == frozenset({
            TransactionState.VALIDATED, TransactionState.ROLLED_BACK,
        })

    def test_can_advance_true(self) -> None:
        assert _make_txn().can_advance(TransactionState.VALIDATED)

    def test_can_advance_false(self) -> None:
        assert not _make_txn().can_advance(TransactionState.FINALIZED)


# ── Advance (happy path) ──────────────────────────────────────


@pytest.mark.unit
class TestAdvanceHappyPath:
    def test_proposed_to_validated(self) -> None:
        txn = _make_txn().advance(TransactionState.VALIDATED)
        assert txn.state is TransactionState.VALIDATED

    def test_full_lifecycle(self) -> None:
        txn = _make_txn()
        txn = txn.advance(TransactionState.VALIDATED)
        txn = txn.advance(TransactionState.COMMITTED)
        txn = txn.advance(TransactionState.FINALIZED)
        assert txn.state is TransactionState.FINALIZED
        assert txn.is_terminal

    def test_proposed_to_rolled_back(self) -> None:
        txn = _make_txn().advance(TransactionState.ROLLED_BACK)
        assert txn.state is TransactionState.ROLLED_BACK
        assert txn.is_terminal

    def test_validated_to_rolled_back(self) -> None:
        txn = (_make_txn()
               .advance(TransactionState.VALIDATED)
               .advance(TransactionState.ROLLED_BACK))
        assert txn.state is TransactionState.ROLLED_BACK

    def test_advance_preserves_transaction_id(self) -> None:
        txn = _make_txn()
        advanced = txn.advance(TransactionState.VALIDATED)
        assert advanced.transaction_id == txn.transaction_id

    def test_advance_preserves_created_at(self) -> None:
        txn = _make_txn()
        advanced = txn.advance(TransactionState.VALIDATED)
        assert advanced.created_at == txn.created_at

    def test_advance_updates_updated_at(self) -> None:
        txn = _make_txn()
        t = txn.updated_at
        advanced = txn.advance(TransactionState.VALIDATED)
        assert advanced.updated_at >= t

    def test_advance_with_actor_override(self) -> None:
        txn = _make_txn(actor_id="alice")
        advanced = txn.advance(TransactionState.VALIDATED, actor_id="bob")
        assert advanced.actor_id == "bob"

    def test_advance_inherits_actor_when_not_specified(self) -> None:
        txn = _make_txn(actor_id="alice")
        advanced = txn.advance(TransactionState.VALIDATED)
        assert advanced.actor_id == "alice"

    def test_advance_metadata_merge(self) -> None:
        txn = _make_txn(metadata={"key1": "value1"})
        advanced = txn.advance(
            TransactionState.VALIDATED,
            metadata_update={"key2": "value2"},
        )
        assert advanced.metadata == {"key1": "value1", "key2": "value2"}

    def test_advance_metadata_override(self) -> None:
        txn = _make_txn(metadata={"key1": "old"})
        advanced = txn.advance(
            TransactionState.VALIDATED,
            metadata_update={"key1": "new"},
        )
        assert advanced.metadata["key1"] == "new"


# ── Advance (illegal transitions) ─────────────────────────────


@pytest.mark.unit
class TestAdvanceIllegal:
    def test_proposed_to_committed_raises(self) -> None:
        with pytest.raises(IllegalTransitionError) as exc_info:
            _make_txn().advance(TransactionState.COMMITTED)
        assert exc_info.value.current is TransactionState.PROPOSED
        assert exc_info.value.target is TransactionState.COMMITTED

    def test_proposed_to_finalized_raises(self) -> None:
        with pytest.raises(IllegalTransitionError):
            _make_txn().advance(TransactionState.FINALIZED)

    def test_committed_to_rolled_back_raises(self) -> None:
        txn = (_make_txn()
               .advance(TransactionState.VALIDATED)
               .advance(TransactionState.COMMITTED))
        with pytest.raises(IllegalTransitionError):
            txn.advance(TransactionState.ROLLED_BACK)

    def test_finalized_to_anything_raises(self) -> None:
        txn = (_make_txn()
               .advance(TransactionState.VALIDATED)
               .advance(TransactionState.COMMITTED)
               .advance(TransactionState.FINALIZED))
        for target in TransactionState:
            with pytest.raises(IllegalTransitionError):
                txn.advance(target)

    def test_rolled_back_to_anything_raises(self) -> None:
        txn = _make_txn().advance(TransactionState.ROLLED_BACK)
        for target in TransactionState:
            with pytest.raises(IllegalTransitionError):
                txn.advance(target)

    def test_error_message_contains_states(self) -> None:
        with pytest.raises(IllegalTransitionError, match="PROPOSED.*COMMITTED"):
            _make_txn().advance(TransactionState.COMMITTED)


# ── History tracking ──────────────────────────────────────────


@pytest.mark.unit
class TestHistory:
    def test_history_grows_on_advance(self) -> None:
        txn = _make_txn()
        assert len(txn.history) == 0
        txn = txn.advance(TransactionState.VALIDATED, actor_id="alice")
        assert len(txn.history) == 1
        txn = txn.advance(TransactionState.COMMITTED, actor_id="bob")
        assert len(txn.history) == 2

    def test_history_records_state_and_actor(self) -> None:
        txn = _make_txn().advance(TransactionState.VALIDATED, actor_id="alice")
        state_val, actor, ts = txn.history[0]
        assert state_val == "VALIDATED"
        assert actor == "alice"
        assert isinstance(ts, float)

    def test_full_lifecycle_history(self) -> None:
        txn = (_make_txn(actor_id="sys")
               .advance(TransactionState.VALIDATED, actor_id="validator")
               .advance(TransactionState.COMMITTED, actor_id="approver")
               .advance(TransactionState.FINALIZED, actor_id="system"))
        assert len(txn.history) == 3
        states = [s for s, _, _ in txn.history]
        assert states == ["VALIDATED", "COMMITTED", "FINALIZED"]


# ── Immutability ──────────────────────────────────────────────


@pytest.mark.unit
class TestImmutability:
    def test_frozen_dataclass(self) -> None:
        txn = _make_txn()
        with pytest.raises(AttributeError):
            txn.state = TransactionState.VALIDATED  # type: ignore[misc]

    def test_advance_returns_new_instance(self) -> None:
        original = _make_txn()
        advanced = original.advance(TransactionState.VALIDATED)
        assert original is not advanced
        assert original.state is TransactionState.PROPOSED
        assert advanced.state is TransactionState.VALIDATED


# ── Serialization ─────────────────────────────────────────────


@pytest.mark.unit
class TestSerialization:
    def test_to_dict_basic(self) -> None:
        txn = _make_txn(operation="invite_user", actor_id="root")
        d = txn.to_dict()
        assert d["state"] == "PROPOSED"
        assert d["operation"] == "invite_user"
        assert d["actor_id"] == "root"
        assert isinstance(d["history"], list)

    def test_roundtrip(self) -> None:
        txn = (_make_txn(operation="stage_file", actor_id="da1",
                         metadata={"template": "profile"})
               .advance(TransactionState.VALIDATED, actor_id="da1")
               .advance(TransactionState.COMMITTED, actor_id="root"))
        d = txn.to_dict()
        restored = StateTransaction.from_dict(d)
        assert restored.transaction_id == txn.transaction_id
        assert restored.state is txn.state
        assert restored.operation == txn.operation
        assert restored.actor_id == txn.actor_id
        assert restored.metadata == txn.metadata
        assert len(restored.history) == len(txn.history)

    def test_from_dict_history_format(self) -> None:
        txn = _make_txn().advance(TransactionState.VALIDATED, actor_id="alice")
        d = txn.to_dict()
        # History in to_dict is list of dicts
        assert isinstance(d["history"][0], dict)
        assert d["history"][0]["state"] == "VALIDATED"
        # Roundtrip restores tuple format
        restored = StateTransaction.from_dict(d)
        state_val, actor, ts = restored.history[0]
        assert state_val == "VALIDATED"
        assert actor == "alice"

    def test_to_dict_state_is_string(self) -> None:
        txn = _make_txn()
        assert isinstance(txn.to_dict()["state"], str)


# ── Tool adapter ──────────────────────────────────────────────


@pytest.mark.unit
class TestToolAdapter:
    @pytest.fixture(autouse=True)
    def _load_adapter(self) -> None:
        import importlib.util
        from pathlib import Path
        adapter_path = (
            Path(__file__).resolve().parents[1]
            / "model-packs" / "system" / "controllers"
            / "state_transaction_adapter.py"
        )
        spec = importlib.util.spec_from_file_location(
            "state_transaction_adapter", adapter_path,
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self._adapter = mod

    def test_info_returns_state(self) -> None:
        txn = (_make_txn(operation="test_op")
               .advance(TransactionState.VALIDATED))
        result = self._adapter.state_transaction_info({"transaction": txn.to_dict()})
        assert result["state"] == "VALIDATED"
        assert result["is_terminal"] is False
        assert "COMMITTED" in result["legal_targets"]

    def test_info_invalid_payload(self) -> None:
        result = self._adapter.state_transaction_info({})
        assert "error" in result

    def test_advance_via_adapter(self) -> None:
        txn = _make_txn().advance(TransactionState.VALIDATED)
        result = self._adapter.state_transaction_advance({
            "transaction": txn.to_dict(),
            "target_state": "COMMITTED",
            "actor_id": "root",
        })
        assert "transaction" in result
        assert result["transaction"]["state"] == "COMMITTED"

    def test_advance_illegal_via_adapter(self) -> None:
        txn = _make_txn()  # PROPOSED
        result = self._adapter.state_transaction_advance({
            "transaction": txn.to_dict(),
            "target_state": "FINALIZED",
            "actor_id": "root",
        })
        assert "error" in result

    def test_advance_unknown_state_via_adapter(self) -> None:
        txn = _make_txn()
        result = self._adapter.state_transaction_advance({
            "transaction": txn.to_dict(),
            "target_state": "NONEXISTENT",
            "actor_id": "root",
        })
        assert "error" in result
        assert "valid_states" in result
