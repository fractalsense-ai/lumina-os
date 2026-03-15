"""
Tests for the system-physics CTL commitment gate.

Covers:
  1. NullPersistenceAdapter stubs return safe defaults (no blocking in tests)
  2. FilesystemPersistenceAdapter correctly detects missing commitment
  3. FilesystemPersistenceAdapter detects present commitment after append
  4. Appended system CTL record forms a valid hash chain
  5. PPAOrchestrator injects system_physics_hash into TraceEvent metadata
  6. PPAOrchestrator injects system_physics_hash into EscalationRecord metadata
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.persistence.filesystem import FilesystemPersistenceAdapter


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _make_commitment_record(
    subject_hash: str,
    prev_hash: str = "genesis",
    subject_id: str = "lumina.system.ci",
) -> dict[str, Any]:
    return {
        "record_type": "CommitmentRecord",
        "record_id": str(uuid.uuid4()),
        "prev_record_hash": prev_hash,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "actor_id": "test-actor",
        "actor_role": "system_operator",
        "commitment_type": "system_physics_activation",
        "subject_id": subject_id,
        "subject_version": "1.0.0",
        "subject_hash": subject_hash,
        "summary": "test commitment",
        "references": [],
        "metadata": {},
    }


def _canonical_hash(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# ─────────────────────────────────────────────────────────────
# Test 1: NullPersistenceAdapter stubs
# ─────────────────────────────────────────────────────────────

def test_null_adapter_system_stubs():
    adapter = NullPersistenceAdapter()

    # get_system_ctl_ledger_path should return a non-empty string
    path = adapter.get_system_ctl_ledger_path()
    assert isinstance(path, str) and path

    # has_system_physics_commitment must return True (no gate blocking in tests)
    assert adapter.has_system_physics_commitment("any-hash") is True

    # append_system_ctl_record must be a no-op (no errors)
    adapter.append_system_ctl_record({"record_type": "CommitmentRecord"})


# ─────────────────────────────────────────────────────────────
# Test 2: Filesystem adapter — commitment missing
# ─────────────────────────────────────────────────────────────

def test_filesystem_no_commitment(tmp_path):
    adapter = FilesystemPersistenceAdapter(repo_root=tmp_path, ctl_dir=tmp_path / "ctl")

    fake_hash = "a" * 64
    assert adapter.has_system_physics_commitment(fake_hash) is False


# ─────────────────────────────────────────────────────────────
# Test 3: Filesystem adapter — commitment present after append
# ─────────────────────────────────────────────────────────────

def test_filesystem_commitment_present(tmp_path):
    adapter = FilesystemPersistenceAdapter(repo_root=tmp_path, ctl_dir=tmp_path / "ctl")

    fake_hash = "b" * 64
    record = _make_commitment_record(fake_hash)
    adapter.append_system_ctl_record(record)

    assert adapter.has_system_physics_commitment(fake_hash) is True
    # Different hash must still return False
    assert adapter.has_system_physics_commitment("c" * 64) is False


# ─────────────────────────────────────────────────────────────
# Test 4: Appended system CTL chain is hash-chain valid
# ─────────────────────────────────────────────────────────────

def test_filesystem_system_ctl_chain_valid(tmp_path):
    adapter = FilesystemPersistenceAdapter(repo_root=tmp_path, ctl_dir=tmp_path / "ctl")

    r1 = _make_commitment_record("d" * 64, prev_hash="genesis")
    adapter.append_system_ctl_record(r1)

    r1_hash = _canonical_hash(r1)
    r2 = _make_commitment_record("e" * 64, prev_hash=r1_hash)
    adapter.append_system_ctl_record(r2)

    # Read the ledger back and verify via validate_ctl_chain (scope="all")
    result = adapter.validate_ctl_chain()
    # The "system" sentinel will be included in the all-scope results
    system_result = next(
        (r for r in result.get("results", []) if r.get("session_id") == "system"),
        None,
    )
    assert system_result is not None, "System CTL missing from validate_ctl_chain results"
    assert system_result["intact"] is True
    assert system_result["records_checked"] == 2


# ─────────────────────────────────────────────────────────────
# Test 5: PPAOrchestrator injects hash into TraceEvent metadata
# ─────────────────────────────────────────────────────────────

def test_orchestrator_trace_event_hash_injection(tmp_path):
    """system_physics_hash is present in TraceEvent.metadata after a turn."""
    from lumina.orchestrator.ppa_orchestrator import PPAOrchestrator

    domain = _minimal_domain()
    profile = _minimal_profile()

    fake_hash = "f" * 64
    orch = PPAOrchestrator(
        domain_physics=domain,
        subject_profile=profile,
        ledger_path=str(tmp_path / "test.jsonl"),
        session_id="test-session",
        system_physics_hash=fake_hash,
    )

    # Simulate a minimal TraceEvent write
    orch._write_trace_event(
        task_spec={"task_id": "t1"},
        invariant_results=[],
        domain_lib_decision={},
        action="EXPLAIN",
        prompt_contract={"prompt_type": "explain"},
    )

    trace_records = [r for r in orch.ctl_records if r.get("record_type") == "TraceEvent"]
    assert trace_records, "No TraceEvent written"
    assert trace_records[0]["metadata"].get("system_physics_hash") == fake_hash


# ─────────────────────────────────────────────────────────────
# Test 6: PPAOrchestrator injects hash into EscalationRecord metadata
# ─────────────────────────────────────────────────────────────

def test_orchestrator_escalation_hash_injection(tmp_path):
    """system_physics_hash is present in EscalationRecord.metadata."""
    from lumina.orchestrator.ppa_orchestrator import PPAOrchestrator

    domain = _minimal_domain()
    profile = _minimal_profile()

    fake_hash = "0" * 64
    orch = PPAOrchestrator(
        domain_physics=domain,
        subject_profile=profile,
        ledger_path=str(tmp_path / "test2.jsonl"),
        session_id="test-session-2",
        system_physics_hash=fake_hash,
    )

    orch._write_escalation_record(
        task_spec={"task_id": "t2"},
        domain_lib_decision={},
        trigger="test_trigger",
    )

    escalation_records = [r for r in orch.ctl_records if r.get("record_type") == "EscalationRecord"]
    assert escalation_records, "No EscalationRecord written"
    assert escalation_records[0]["metadata"].get("system_physics_hash") == fake_hash


# ─────────────────────────────────────────────────────────────
# Domain / profile factories for orchestrator tests
# ─────────────────────────────────────────────────────────────

def _minimal_domain() -> dict[str, Any]:
    return {
        "id": "test-domain",
        "version": "0.1.0",
        "invariants": [],
        "standing_orders": [],
        "escalation_triggers": [],
        "domain_authority": {"pseudonymous_id": "test-actor"},
    }


def _minimal_profile() -> dict[str, Any]:
    return {
        "subject_id": "test-student",
        "display_name": "Test Student",
    }
