"""
lumina-security-freeze.py — Project Lumina Emergency Security Freeze CLI

Performs an institution-wide security freeze:
    1. Scans all CTL ledger files for chain integrity
    2. Writes a CommitmentRecord (policy_change / security_freeze) to each ledger
    3. Outputs a consolidated integrity report

Usage:
    python reference-implementations/lumina-security-freeze.py \
        --actor-id <pseudonymous-id> \
        --ledger-dir path/to/ledger-directory \
        --reason "Brief explanation of why the freeze was triggered"

Dependencies: standard library only (json, hashlib, argparse, uuid, datetime, pathlib)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ─────────────────────────────────────────────────────────────
# Hash Utilities (same as ctl-commitment-validator.py)
# ─────────────────────────────────────────────────────────────

def canonical_json(record: dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_record(record: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(record))


# ─────────────────────────────────────────────────────────────
# Ledger I/O
# ─────────────────────────────────────────────────────────────

def load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARNING: Invalid JSON on line {line_no} in {path}: {e}", file=sys.stderr)
    return records


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        f.write("\n")


# ─────────────────────────────────────────────────────────────
# Chain Verification
# ─────────────────────────────────────────────────────────────

def verify_chain(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"intact": True, "records_checked": 0, "first_broken_id": None, "error": None}

    first = records[0]
    if first.get("prev_record_hash") != "genesis":
        return {
            "intact": False,
            "records_checked": 1,
            "first_broken_id": first.get("record_id"),
            "error": f"First record prev_record_hash is not 'genesis'",
        }

    for i in range(1, len(records)):
        expected = hash_record(records[i - 1])
        actual = records[i].get("prev_record_hash", "")
        if actual != expected:
            return {
                "intact": False,
                "records_checked": i + 1,
                "first_broken_id": records[i].get("record_id"),
                "error": f"Hash mismatch at index {i}",
            }

    return {"intact": True, "records_checked": len(records), "first_broken_id": None, "error": None}


# ─────────────────────────────────────────────────────────────
# Security Freeze
# ─────────────────────────────────────────────────────────────

def find_ledger_files(ledger_dir: Path) -> list[Path]:
    return sorted(ledger_dir.rglob("*.jsonl"))


def run_security_freeze(actor_id: str, ledger_dir: Path, reason: str) -> int:
    ledger_files = find_ledger_files(ledger_dir)

    if not ledger_files:
        print(f"No ledger files (*.jsonl) found under {ledger_dir}")
        return 1

    print("═" * 60)
    print("PROJECT LUMINA — SECURITY FREEZE")
    print("═" * 60)
    print(f"  Actor:      {actor_id}")
    print(f"  Ledger dir: {ledger_dir}")
    print(f"  Reason:     {reason}")
    print(f"  Ledgers:    {len(ledger_files)} file(s)")
    print("═" * 60)

    confirmation = input("Type 'FREEZE' to confirm institution-wide security freeze: ")
    if confirmation.strip() != "FREEZE":
        print("Aborted.")
        return 1

    timestamp = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        "freeze_id": str(uuid.uuid4()),
        "timestamp_utc": timestamp,
        "actor_id": actor_id,
        "reason": reason,
        "ledgers": [],
    }
    all_intact = True

    for ledger_path in ledger_files:
        records = load_ledger(ledger_path)
        integrity = verify_chain(records)
        ledger_name = str(ledger_path.relative_to(ledger_dir))

        ledger_report: dict[str, Any] = {
            "file": ledger_name,
            "records_checked": integrity["records_checked"],
            "chain_intact": integrity["intact"],
        }
        if not integrity["intact"]:
            all_intact = False
            ledger_report["error"] = integrity["error"]
            ledger_report["first_broken_id"] = integrity["first_broken_id"]

        # Append freeze CommitmentRecord to each ledger
        prev_hash = hash_record(records[-1]) if records else "genesis"
        freeze_record: dict[str, Any] = {
            "record_type": "CommitmentRecord",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": prev_hash,
            "timestamp_utc": timestamp,
            "actor_id": actor_id,
            "actor_role": "administration",
            "commitment_type": "policy_change",
            "subject_id": ledger_name,
            "summary": f"Security freeze: {reason}",
            "references": [],
            "metadata": {"action": "security_freeze", "reason": reason},
        }
        append_record(ledger_path, freeze_record)
        ledger_report["freeze_record_id"] = freeze_record["record_id"]
        report["ledgers"].append(ledger_report)

    report["overall_integrity"] = "INTACT" if all_intact else "BROKEN"

    # Output report
    print()
    print("═" * 60)
    print("SECURITY FREEZE REPORT")
    print("═" * 60)
    print(f"  Freeze ID:          {report['freeze_id']}")
    print(f"  Timestamp:          {report['timestamp_utc']}")
    print(f"  Overall Integrity:  {report['overall_integrity']}")
    print()

    for lr in report["ledgers"]:
        status = "INTACT ✓" if lr["chain_intact"] else "BROKEN ✗"
        print(f"  {lr['file']}")
        print(f"    Records: {lr['records_checked']}  Chain: {status}")
        print(f"    Freeze record: {lr['freeze_record_id']}")
        if not lr["chain_intact"]:
            print(f"    ERROR: {lr.get('error', 'unknown')}")
        print()

    print("═" * 60)
    print(json.dumps(report, indent=2))
    return 0 if all_intact else 2  # 2 = freeze succeeded but integrity issues found


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project Lumina — Emergency institution-wide security freeze.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--actor-id", required=True,
        help="Pseudonymous ID of the administrator executing the freeze.",
    )
    parser.add_argument(
        "--ledger-dir", required=True,
        help="Root directory containing CTL ledger files (*.jsonl).",
    )
    parser.add_argument(
        "--reason", required=True,
        help="Brief explanation for the security freeze.",
    )

    args = parser.parse_args()
    sys.exit(run_security_freeze(
        actor_id=args.actor_id,
        ledger_dir=Path(args.ledger_dir),
        reason=args.reason,
    ))


if __name__ == "__main__":
    main()
