"""Additional tests for lumina.systools.system_log_validator: command functions and utilities."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

import lumina.systools.system_log_validator as ctl_mod
from lumina.systools.system_log_validator import (
    canonical_file_hash,
    canonical_json,
    cmd_commit,
    cmd_print_ledger,
    cmd_verify_chain,
    cmd_verify_session,
    cmd_verify_system_chain,
    hash_file,
    hash_record,
    load_ledger,
    append_record,
    sha256_hex,
)


# ── Hash utility tests ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_canonical_json_produces_sorted_bytes() -> None:
    rec = {"z": 1, "a": 2, "m": 3}
    result = canonical_json(rec)
    assert isinstance(result, bytes)
    parsed = json.loads(result)
    assert parsed == {"a": 2, "m": 3, "z": 1}
    # Must be compact (no whitespace)
    assert b" " not in result


@pytest.mark.unit
def test_sha256_hex_returns_64_char_hex() -> None:
    result = sha256_hex(b"hello world")
    assert len(result) == 64
    assert result == hashlib.sha256(b"hello world").hexdigest()


@pytest.mark.unit
def test_hash_record_deterministic() -> None:
    rec = {"record_type": "TraceEvent", "record_id": "r1", "prev_record_hash": "genesis"}
    h1 = hash_record(rec)
    h2 = hash_record(rec)
    assert h1 == h2
    assert len(h1) == 64


@pytest.mark.unit
def test_hash_file_reads_bytes(tmp_path: Path) -> None:
    f = tmp_path / "file.bin"
    f.write_bytes(b"data content")
    expected = hashlib.sha256(b"data content").hexdigest()
    assert hash_file(f) == expected


@pytest.mark.unit
def test_canonical_file_hash_uses_canonical_json(tmp_path: Path) -> None:
    data = {"id": "test", "version": "1.0.0", "z": True, "a": False}
    f = tmp_path / "data.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    expected = sha256_hex(canonical_json(data))
    assert canonical_file_hash(f) == expected


# ── cmd_verify_chain ──────────────────────────────────────────────────────────


def _make_intact_ledger(tmp_path: Path, n: int = 2) -> Path:
    """Write an n-record intact ledger to tmp_path/ledger.jsonl."""
    ledger = tmp_path / "ledger.jsonl"
    prev = "genesis"
    for i in range(n):
        rec: dict[str, Any] = {
            "record_type": "TraceEvent",
            "record_id": f"r{i}",
            "prev_record_hash": prev,
            "event_type": "turn",
        }
        append_record(ledger, rec)
        prev = hash_record(rec)
    return ledger


@pytest.mark.unit
def test_cmd_verify_chain_intact(tmp_path: Path) -> None:
    ledger = _make_intact_ledger(tmp_path, 3)
    args = argparse.Namespace(ledger=str(ledger))
    assert cmd_verify_chain(args) == 0


@pytest.mark.unit
def test_cmd_verify_chain_broken(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    r1 = {"record_type": "TraceEvent", "record_id": "r1", "prev_record_hash": "genesis"}
    r2 = {"record_type": "TraceEvent", "record_id": "r2", "prev_record_hash": "WRONG_HASH"}
    append_record(ledger, r1)
    append_record(ledger, r2)
    args = argparse.Namespace(ledger=str(ledger))
    assert cmd_verify_chain(args) == 1


@pytest.mark.unit
def test_cmd_verify_chain_empty_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "empty.jsonl"
    args = argparse.Namespace(ledger=str(ledger))
    assert cmd_verify_chain(args) == 0


# ── cmd_verify_session ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cmd_verify_session_found(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    session_id = "test-session-uuid"
    r1: dict[str, Any] = {
        "record_type": "TraceEvent",
        "record_id": "r1",
        "prev_record_hash": "genesis",
        "session_id": session_id,
        "event_type": "turn",
    }
    append_record(ledger, r1)

    args = argparse.Namespace(ledger=str(ledger), verify_session=session_id)
    result = cmd_verify_session(args)
    assert result == 0


@pytest.mark.unit
def test_cmd_verify_session_not_found(tmp_path: Path) -> None:
    ledger = _make_intact_ledger(tmp_path, 1)
    args = argparse.Namespace(ledger=str(ledger), verify_session="nonexistent-session")
    assert cmd_verify_session(args) == 1


@pytest.mark.unit
def test_cmd_verify_session_broken_global_chain(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    session_id = "s1"
    r1: dict[str, Any] = {
        "record_type": "TraceEvent",
        "record_id": "r1",
        "prev_record_hash": "genesis",
        "session_id": session_id,
    }
    r2: dict[str, Any] = {
        "record_type": "TraceEvent",
        "record_id": "r2",
        "prev_record_hash": "BAD",
        "session_id": session_id,
    }
    append_record(ledger, r1)
    append_record(ledger, r2)

    args = argparse.Namespace(ledger=str(ledger), verify_session=session_id)
    assert cmd_verify_session(args) == 1


# ── cmd_commit ────────────────────────────────────────────────────────────────


def _make_physics_file(tmp_path: Path, name: str = "domain-physics.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({"id": "test-domain", "version": "1.0.0"}), encoding="utf-8")
    return p


@pytest.mark.unit
def test_cmd_commit_to_empty_ledger(tmp_path: Path) -> None:
    subject = _make_physics_file(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    args = argparse.Namespace(
        commit=str(subject),
        ledger=str(ledger),
        actor_id="actor-1",
        commitment_type=None,
        summary=None,
    )
    result = cmd_commit(args)
    assert result == 0
    records = load_ledger(ledger)
    assert len(records) == 1
    assert records[0]["record_type"] == "CommitmentRecord"
    assert records[0]["prev_record_hash"] == "genesis"


@pytest.mark.unit
def test_cmd_commit_appends_with_correct_prev_hash(tmp_path: Path) -> None:
    subject = _make_physics_file(tmp_path)
    ledger = _make_intact_ledger(tmp_path, 1)
    first_records = load_ledger(ledger)
    expected_prev = hash_record(first_records[-1])

    args = argparse.Namespace(
        commit=str(subject),
        ledger=str(ledger),
        actor_id="actor-1",
        commitment_type="model_pack_activation",
        summary="My summary",
    )
    cmd_commit(args)
    records = load_ledger(ledger)
    assert records[-1]["prev_record_hash"] == expected_prev


@pytest.mark.unit
def test_cmd_commit_missing_subject(tmp_path: Path) -> None:
    args = argparse.Namespace(
        commit=str(tmp_path / "nonexistent.json"),
        ledger=str(tmp_path / "ledger.jsonl"),
        actor_id="actor-1",
        commitment_type=None,
        summary=None,
    )
    assert cmd_commit(args) == 1


# ── cmd_print_ledger ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cmd_print_ledger_empty(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    ledger = tmp_path / "empty.jsonl"
    args = argparse.Namespace(print_ledger=str(ledger))
    result = cmd_print_ledger(args)
    assert result == 0
    out = capsys.readouterr().out
    assert "empty" in out.lower() or "does not exist" in out.lower()


@pytest.mark.unit
def test_cmd_print_ledger_trace_event(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    ledger = _make_intact_ledger(tmp_path, 2)
    args = argparse.Namespace(print_ledger=str(ledger))
    result = cmd_print_ledger(args)
    assert result == 0
    out = capsys.readouterr().out
    assert "TraceEvent" in out


@pytest.mark.unit
def test_cmd_print_ledger_commitment_record(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    subject = _make_physics_file(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    commit_args = argparse.Namespace(
        commit=str(subject),
        ledger=str(ledger),
        actor_id="actor-test",
        commitment_type="model_pack_activation",
        summary=None,
    )
    cmd_commit(commit_args)

    args = argparse.Namespace(print_ledger=str(ledger))
    result = cmd_print_ledger(args)
    assert result == 0
    out = capsys.readouterr().out
    assert "CommitmentRecord" in out


@pytest.mark.unit
def test_cmd_print_ledger_escalation_record(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rec: dict[str, Any] = {
        "record_type": "EscalationRecord",
        "record_id": "e1",
        "prev_record_hash": "genesis",
        "session_id": "s1",
        "status": "pending",
        "trigger": "domain_boundary",
    }
    append_record(ledger, rec)
    args = argparse.Namespace(print_ledger=str(ledger))
    result = cmd_print_ledger(args)
    assert result == 0
    out = capsys.readouterr().out
    assert "EscalationRecord" in out


# ── cmd_verify_system_chain ───────────────────────────────────────────────────


@pytest.mark.unit
def test_cmd_verify_system_chain_intact(tmp_path: Path) -> None:
    log_dir = tmp_path / "ctl"
    system_dir = log_dir / "system"
    system_dir.mkdir(parents=True)
    ledger = system_dir / "system.jsonl"
    r1 = {"record_type": "CommitmentRecord", "record_id": "s1", "prev_record_hash": "genesis"}
    append_record(ledger, r1)

    args = argparse.Namespace(log_dir=str(log_dir), system_physics_file=None)
    result = cmd_verify_system_chain(args)
    assert result == 0


@pytest.mark.unit
def test_cmd_verify_system_chain_empty(tmp_path: Path) -> None:
    log_dir = tmp_path / "ctl"
    (log_dir / "system").mkdir(parents=True)

    args = argparse.Namespace(log_dir=str(log_dir), system_physics_file=None)
    result = cmd_verify_system_chain(args)
    assert result == 0


@pytest.mark.unit
def test_cmd_verify_system_chain_broken(tmp_path: Path) -> None:
    log_dir = tmp_path / "ctl"
    system_dir = log_dir / "system"
    system_dir.mkdir(parents=True)
    ledger = system_dir / "system.jsonl"
    r1 = {"record_type": "CommitmentRecord", "record_id": "s1", "prev_record_hash": "genesis"}
    r2 = {"record_type": "CommitmentRecord", "record_id": "s2", "prev_record_hash": "BAD"}
    append_record(ledger, r1)
    append_record(ledger, r2)

    args = argparse.Namespace(log_dir=str(log_dir), system_physics_file=None)
    result = cmd_verify_system_chain(args)
    assert result == 1


@pytest.mark.unit
def test_cmd_verify_system_chain_with_physics_file_found(tmp_path: Path) -> None:
    log_dir = tmp_path / "ctl"
    system_dir = log_dir / "system"
    system_dir.mkdir(parents=True)
    ledger = system_dir / "system.jsonl"
    physics = tmp_path / "system-physics.json"
    physics.write_text(json.dumps({"id": "sys", "version": "1.0"}), encoding="utf-8")
    expected_hash = canonical_file_hash(physics)

    r1: dict[str, Any] = {
        "record_type": "CommitmentRecord",
        "record_id": "s1",
        "prev_record_hash": "genesis",
        "commitment_type": "system_physics_activation",
        "subject_hash": expected_hash,
    }
    append_record(ledger, r1)

    args = argparse.Namespace(log_dir=str(log_dir), system_physics_file=str(physics))
    assert cmd_verify_system_chain(args) == 0


@pytest.mark.unit
def test_cmd_verify_system_chain_with_physics_file_missing_hash(tmp_path: Path) -> None:
    log_dir = tmp_path / "ctl"
    system_dir = log_dir / "system"
    system_dir.mkdir(parents=True)
    ledger = system_dir / "system.jsonl"
    physics = tmp_path / "system-physics.json"
    physics.write_text(json.dumps({"id": "sys", "version": "1.0"}), encoding="utf-8")

    r1 = {"record_type": "CommitmentRecord", "record_id": "s1", "prev_record_hash": "genesis",
           "commitment_type": "system_physics_activation", "subject_hash": "different_hash"}
    append_record(ledger, r1)

    args = argparse.Namespace(log_dir=str(log_dir), system_physics_file=str(physics))
    assert cmd_verify_system_chain(args) == 1


@pytest.mark.unit
def test_cmd_verify_system_chain_physics_file_not_found(tmp_path: Path) -> None:
    log_dir = tmp_path / "ctl"
    (log_dir / "system").mkdir(parents=True)

    args = argparse.Namespace(log_dir=str(log_dir), system_physics_file=str(tmp_path / "nope.json"))
    result = cmd_verify_system_chain(args)
    assert result == 1
