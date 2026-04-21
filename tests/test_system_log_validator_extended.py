"""Extended tests for lumina.systools.system_log_validator — edge cases not yet covered.

Covers:
  - load_ledger with invalid JSON (sys.exit path)
  - verify_chain when first record has non-genesis prev_record_hash
  - cmd_rollback: no prior activation (else branch), abort path, and confirm path
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import lumina.systools.system_log_validator as ctl_mod
from lumina.systools.system_log_validator import (
    append_record,
    canonical_file_hash,
    cmd_rollback,
    hash_record,
    load_ledger,
    verify_chain,
)


# ── load_ledger — invalid JSON ────────────────────────────────────────────────


@pytest.mark.unit
def test_load_ledger_invalid_json_calls_sys_exit(tmp_path: Path) -> None:
    """load_ledger prints an error and calls sys.exit(1) on invalid JSON."""
    ledger = tmp_path / "bad.jsonl"
    ledger.write_text('{"valid": true}\nNOT VALID JSON\n', encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        load_ledger(ledger)
    assert exc_info.value.code == 1


@pytest.mark.unit
def test_load_ledger_empty_lines_are_skipped(tmp_path: Path) -> None:
    """load_ledger skips empty lines without error."""
    ledger = tmp_path / "spaced.jsonl"
    rec = {"record_type": "TraceEvent", "record_id": "r1", "prev_record_hash": "genesis"}
    ledger.write_text(
        "\n"
        + json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n"
        + "\n",
        encoding="utf-8",
    )
    records = load_ledger(ledger)
    assert len(records) == 1
    assert records[0]["record_id"] == "r1"


# ── verify_chain — first record not genesis ───────────────────────────────────


@pytest.mark.unit
def test_verify_chain_first_record_not_genesis() -> None:
    """verify_chain returns broken when first record does not have 'genesis' prev_hash."""
    records = [
        {
            "record_type": "TraceEvent",
            "record_id": "r1",
            "prev_record_hash": "NOT_GENESIS",  # invalid for first record
        }
    ]
    result = verify_chain(records)
    assert result["intact"] is False
    assert result["first_broken_id"] == "r1"
    assert result["records_checked"] == 1
    assert "genesis" in result["error"].lower()


@pytest.mark.unit
def test_verify_chain_single_intact_record() -> None:
    """verify_chain with a single valid record (genesis) returns intact = True."""
    records = [
        {
            "record_type": "TraceEvent",
            "record_id": "r1",
            "prev_record_hash": "genesis",
        }
    ]
    result = verify_chain(records)
    assert result["intact"] is True
    assert result["records_checked"] == 1


# ── cmd_rollback ──────────────────────────────────────────────────────────────


def _make_subject_file(tmp_path: Path) -> Path:
    """Create a domain-physics.json for rollback tests."""
    f = tmp_path / "domain-physics.json"
    f.write_text(json.dumps({"id": "edu-algebra", "version": "2.0.0"}), encoding="utf-8")
    return f


@pytest.mark.unit
def test_cmd_rollback_missing_subject_file(tmp_path: Path) -> None:
    """cmd_rollback returns 1 when the subject file does not exist."""
    args = argparse.Namespace(
        rollback=str(tmp_path / "nonexistent.json"),
        ledger=str(tmp_path / "ledger.jsonl"),
        actor_id="actor-001",
        reason="test rollback",
    )
    assert cmd_rollback(args) == 1


@pytest.mark.unit
def test_cmd_rollback_abort_on_wrong_confirmation(tmp_path: Path) -> None:
    """cmd_rollback returns 1 and prints 'Aborted.' when confirmation != 'ROLLBACK'."""
    subject = _make_subject_file(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    args = argparse.Namespace(
        rollback=str(subject),
        ledger=str(ledger),
        actor_id="actor-001",
        reason="test abort",
    )
    with patch("builtins.input", return_value="no"):
        result = cmd_rollback(args)
    assert result == 1


@pytest.mark.unit
def test_cmd_rollback_confirms_and_appends_record(tmp_path: Path) -> None:
    """cmd_rollback returns 0 and appends a CommitmentRecord when confirmed with 'ROLLBACK'."""
    subject = _make_subject_file(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    # Create an existing ledger with a prior activation
    prior: dict[str, Any] = {
        "record_type": "CommitmentRecord",
        "record_id": "prior-001",
        "prev_record_hash": "genesis",
        "commitment_type": "domain_pack_activation",
        "subject_id": "edu-algebra",
        "subject_hash": canonical_file_hash(subject),
        "actor_id": "actor-001",
        "actor_role": "admin",
    }
    append_record(ledger, prior)

    args = argparse.Namespace(
        rollback=str(subject),
        ledger=str(ledger),
        actor_id="actor-001",
        reason="defective invariant",
    )
    with patch("builtins.input", return_value="ROLLBACK"):
        result = cmd_rollback(args)
    assert result == 0
    records = load_ledger(ledger)
    assert len(records) == 2
    last = records[-1]
    assert last["commitment_type"] == "domain_pack_rollback"
    assert "defective invariant" in last["summary"]
    assert last["references"] == ["prior-001"]


@pytest.mark.unit
def test_cmd_rollback_no_prior_activation_else_branch(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """cmd_rollback handles no prior activation (else branch: 'Prior commit: (none found)')."""
    subject = _make_subject_file(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    # Empty ledger — no prior activation record

    args = argparse.Namespace(
        rollback=str(subject),
        ledger=str(ledger),
        actor_id="actor-001",
        reason="no prior activation",
    )
    with patch("builtins.input", return_value="ROLLBACK"):
        result = cmd_rollback(args)

    assert result == 0
    out = capsys.readouterr().out
    assert "none found" in out.lower()
    records = load_ledger(ledger)
    assert records[-1]["commitment_type"] == "domain_pack_rollback"
    assert records[-1]["references"] == []


# ── main() — CLI entry point ──────────────────────────────────────────────────


@pytest.mark.unit
def test_main_verify_chain_intact(tmp_path: Path) -> None:
    """main() with --verify-chain on a valid ledger exits with code 0."""
    ledger = tmp_path / "ledger.jsonl"
    rec = {"record_type": "TraceEvent", "record_id": "r1", "prev_record_hash": "genesis"}
    append_record(ledger, rec)
    with patch("sys.argv", ["ctl_validator", "--verify-chain", str(ledger)]):
        with pytest.raises(SystemExit) as exc_info:
            ctl_mod.main()
    assert exc_info.value.code == 0


@pytest.mark.unit
def test_main_print_ledger(tmp_path: Path) -> None:
    """main() with --print-ledger exits with code 0."""
    ledger = tmp_path / "ledger.jsonl"
    rec = {"record_type": "TraceEvent", "record_id": "r1", "prev_record_hash": "genesis"}
    append_record(ledger, rec)
    with patch("sys.argv", ["ctl_validator", "--print-ledger", str(ledger)]):
        with pytest.raises(SystemExit) as exc_info:
            ctl_mod.main()
    assert exc_info.value.code == 0


@pytest.mark.unit
def test_main_verify_session(tmp_path: Path) -> None:
    """main() with --verify-session exits with code 0 on intact chain."""
    ledger = tmp_path / "ledger.jsonl"
    rec = {
        "record_type": "TraceEvent",
        "record_id": "r1",
        "prev_record_hash": "genesis",
        "session_id": "sess-abc",
    }
    append_record(ledger, rec)
    with patch(
        "sys.argv",
        ["ctl_validator", "--verify-session", "sess-abc", "--ledger", str(ledger)],
    ):
        with pytest.raises(SystemExit) as exc_info:
            ctl_mod.main()
    assert exc_info.value.code == 0


@pytest.mark.unit
def test_main_commit(tmp_path: Path) -> None:
    """main() with --commit exits with code 0 and appends a CommitmentRecord."""
    subject = tmp_path / "domain-physics.json"
    subject.write_text(json.dumps({"id": "edu/math", "version": "1.0.0"}), encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    with patch(
        "sys.argv",
        [
            "ctl_validator",
            "--commit", str(subject),
            "--ledger", str(ledger),
            "--actor-id", "actor-001",
        ],
    ):
        with pytest.raises(SystemExit) as exc_info:
            ctl_mod.main()
    assert exc_info.value.code == 0


@pytest.mark.unit
def test_main_rollback(tmp_path: Path) -> None:
    """main() with --rollback and confirmation exits with code 0."""
    subject = tmp_path / "domain-physics.json"
    subject.write_text(json.dumps({"id": "edu/math", "version": "1.0.0"}), encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    with patch("builtins.input", return_value="ROLLBACK"):
        with patch(
            "sys.argv",
            [
                "ctl_validator",
                "--rollback", str(subject),
                "--ledger", str(ledger),
                "--actor-id", "actor-001",
                "--reason", "buggy domain pack",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                ctl_mod.main()
    assert exc_info.value.code == 0


@pytest.mark.unit
def test_main_verify_system_chain(tmp_path: Path) -> None:
    """main() with --verify-system-chain on empty dir exits with code 0."""
    log_dir = tmp_path / "log"
    system_dir = log_dir / "system"
    system_dir.mkdir(parents=True)
    ledger = system_dir / "system.jsonl"
    ledger.write_text("", encoding="utf-8")
    with patch(
        "sys.argv",
        ["system_log_validator", "--verify-system-chain", "--log-dir", str(log_dir)],
    ):
        with pytest.raises(SystemExit) as exc_info:
            ctl_mod.main()
    assert exc_info.value.code == 0
