"""Tests for CLI tools: ctl-commitment-validator --rollback and lumina-security-freeze."""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REF_DIR = REPO_ROOT / "reference-implementations"


def _load_module(script_name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(REF_DIR / script_name))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def validator_mod():
    return _load_module("ctl-commitment-validator.py", "ctl_commitment_validator")


@pytest.fixture(scope="module")
def freeze_mod():
    return _load_module("lumina-security-freeze.py", "lumina_security_freeze")


def _write_sample_domain_physics(path: Path) -> None:
    """Write a minimal domain-physics JSON for testing."""
    data = {"id": "test-domain", "version": "1.0.0", "invariants": []}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _seed_ledger_with_activation(mod, ledger_path: Path, subject_path: Path, actor_id: str) -> dict[str, Any]:
    """Commit an activation record and return it."""
    record = mod.build_commitment_record(
        subject_path=subject_path,
        actor_id=actor_id,
        commitment_type="domain_pack_activation",
        prev_record_hash="genesis",
        summary="Initial activation",
    )
    mod.append_record(ledger_path, record)
    return record


# ─────────────────────────────────────────────────────────────
# ctl-commitment-validator --rollback tests
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestRollbackCommand:
    def test_rollback_writes_commitment_record(self, validator_mod, tmp_path: Path) -> None:
        subject = tmp_path / "domain-physics.json"
        _write_sample_domain_physics(subject)
        ledger = tmp_path / "ledger.jsonl"
        _seed_ledger_with_activation(validator_mod, ledger, subject, "actor-1")

        # Simulate confirmed rollback
        with patch("builtins.input", return_value="ROLLBACK"):
            import argparse
            args = argparse.Namespace(
                rollback=str(subject),
                ledger=str(ledger),
                actor_id="actor-1",
                reason="Defective invariant",
            )
            result = validator_mod.cmd_rollback(args)

        assert result == 0
        records = validator_mod.load_ledger(ledger)
        assert len(records) == 2

        rollback_rec = records[-1]
        assert rollback_rec["record_type"] == "CommitmentRecord"
        assert rollback_rec["commitment_type"] == "domain_pack_rollback"
        assert rollback_rec["actor_id"] == "actor-1"
        assert rollback_rec["subject_id"] == "test-domain"
        assert rollback_rec["metadata"]["reason"] == "Defective invariant"
        assert rollback_rec["summary"] == "Rollback: Defective invariant"
        # Should reference the prior activation record
        assert len(rollback_rec["references"]) == 1

    def test_rollback_chain_integrity(self, validator_mod, tmp_path: Path) -> None:
        subject = tmp_path / "domain-physics.json"
        _write_sample_domain_physics(subject)
        ledger = tmp_path / "ledger.jsonl"
        _seed_ledger_with_activation(validator_mod, ledger, subject, "actor-1")

        with patch("builtins.input", return_value="ROLLBACK"):
            import argparse
            args = argparse.Namespace(
                rollback=str(subject),
                ledger=str(ledger),
                actor_id="actor-1",
                reason="Testing chain",
            )
            validator_mod.cmd_rollback(args)

        records = validator_mod.load_ledger(ledger)
        chain_result = validator_mod.verify_chain(records)
        assert chain_result["intact"] is True
        assert chain_result["records_checked"] == 2

    def test_rollback_aborted_on_wrong_confirmation(self, validator_mod, tmp_path: Path) -> None:
        subject = tmp_path / "domain-physics.json"
        _write_sample_domain_physics(subject)
        ledger = tmp_path / "ledger.jsonl"
        _seed_ledger_with_activation(validator_mod, ledger, subject, "actor-1")

        with patch("builtins.input", return_value="no"):
            import argparse
            args = argparse.Namespace(
                rollback=str(subject),
                ledger=str(ledger),
                actor_id="actor-1",
                reason="Aborted test",
            )
            result = validator_mod.cmd_rollback(args)

        assert result == 1
        records = validator_mod.load_ledger(ledger)
        assert len(records) == 1  # Only the original activation

    def test_rollback_subject_not_found(self, validator_mod, tmp_path: Path) -> None:
        import argparse
        args = argparse.Namespace(
            rollback=str(tmp_path / "nonexistent.json"),
            ledger=str(tmp_path / "ledger.jsonl"),
            actor_id="actor-1",
            reason="Does not exist",
        )
        result = validator_mod.cmd_rollback(args)
        assert result == 1


# ─────────────────────────────────────────────────────────────
# lumina-security-freeze tests
# ─────────────────────────────────────────────────────────────


def _create_ledger_with_records(path: Path, freeze_mod, count: int = 3) -> list[dict[str, Any]]:
    """Create a ledger file with `count` TraceEvent records."""
    records = []
    prev_hash = "genesis"
    for i in range(count):
        rec: dict[str, Any] = {
            "record_type": "TraceEvent",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": prev_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": str(uuid.uuid4()),
            "actor_id": f"actor-{i}",
            "event_type": "state_update",
            "decision": f"decision-{i}",
        }
        freeze_mod.append_record(path, rec)
        prev_hash = freeze_mod.hash_record(rec)
        records.append(rec)
    return records


@pytest.mark.integration
class TestSecurityFreeze:
    def test_freeze_writes_commitment_to_all_ledgers(self, freeze_mod, tmp_path: Path) -> None:
        # Create two ledger files in subdirectories
        ledger_a = tmp_path / "sessions" / "session-a.jsonl"
        ledger_b = tmp_path / "admin" / "admin.jsonl"
        _create_ledger_with_records(ledger_a, freeze_mod, 3)
        _create_ledger_with_records(ledger_b, freeze_mod, 2)

        with patch("builtins.input", return_value="FREEZE"):
            result = freeze_mod.run_security_freeze(
                actor_id="admin-root",
                ledger_dir=tmp_path,
                reason="Suspected compromise",
            )

        assert result == 0

        # Each ledger should have a freeze CommitmentRecord appended
        records_a = freeze_mod.load_ledger(ledger_a)
        assert len(records_a) == 4  # 3 original + 1 freeze
        assert records_a[-1]["record_type"] == "CommitmentRecord"
        assert records_a[-1]["commitment_type"] == "policy_change"
        assert records_a[-1]["metadata"]["action"] == "security_freeze"
        assert records_a[-1]["actor_role"] == "administration"

        records_b = freeze_mod.load_ledger(ledger_b)
        assert len(records_b) == 3  # 2 original + 1 freeze
        assert records_b[-1]["commitment_type"] == "policy_change"

    def test_freeze_chain_integrity_preserved(self, freeze_mod, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.jsonl"
        _create_ledger_with_records(ledger, freeze_mod, 5)

        with patch("builtins.input", return_value="FREEZE"):
            freeze_mod.run_security_freeze(
                actor_id="admin-root",
                ledger_dir=tmp_path,
                reason="Integrity check",
            )

        records = freeze_mod.load_ledger(ledger)
        assert len(records) == 6
        chain_result = freeze_mod.verify_chain(records)
        assert chain_result["intact"] is True

    def test_freeze_aborted(self, freeze_mod, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.jsonl"
        _create_ledger_with_records(ledger, freeze_mod, 2)

        with patch("builtins.input", return_value="no"):
            result = freeze_mod.run_security_freeze(
                actor_id="admin-root",
                ledger_dir=tmp_path,
                reason="Aborted test",
            )

        assert result == 1
        records = freeze_mod.load_ledger(ledger)
        assert len(records) == 2  # No freeze record added

    def test_freeze_no_ledgers_found(self, freeze_mod, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = freeze_mod.run_security_freeze(
            actor_id="admin-root",
            ledger_dir=empty_dir,
            reason="Empty dir",
        )

        assert result == 1

    def test_freeze_detects_broken_chain(self, freeze_mod, tmp_path: Path) -> None:
        ledger = tmp_path / "broken.jsonl"
        _create_ledger_with_records(ledger, freeze_mod, 3)

        # Corrupt the chain by inserting a record with wrong prev_hash
        bad_record: dict[str, Any] = {
            "record_type": "TraceEvent",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": "CORRUPTED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": str(uuid.uuid4()),
            "actor_id": "attacker",
            "event_type": "state_update",
            "decision": "tampered",
        }
        freeze_mod.append_record(ledger, bad_record)

        with patch("builtins.input", return_value="FREEZE"):
            result = freeze_mod.run_security_freeze(
                actor_id="admin-root",
                ledger_dir=tmp_path,
                reason="Post-tampering freeze",
            )

        # Exit code 2 = freeze succeeded but integrity issues found
        assert result == 2
