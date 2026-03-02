"""
ctl-commitment-validator.py — Project Lumina CTL Validator & Commitment Tool

Commands:
    --verify-chain     Verify the hash chain of an entire CTL ledger file
    --verify-session   Verify records for a specific session ID
    --commit           Commit a domain pack (or other artifact) hash to the CTL
    --print-ledger     Print all records in a ledger in human-readable form

Usage:
    # Verify entire chain
    python reference-implementations/ctl-commitment-validator.py \\
        --verify-chain path/to/ledger.jsonl

    # Verify a single session
    python reference-implementations/ctl-commitment-validator.py \\
        --verify-session <session-uuid> \\
        --ledger path/to/ledger.jsonl

    # Commit a domain pack hash
    python reference-implementations/ctl-commitment-validator.py \\
        --commit domain-packs/education/algebra-level-1/domain-physics.json \\
        --actor-id <pseudonymous-id> \\
        --ledger path/to/ledger.jsonl

    # Print ledger contents
    python reference-implementations/ctl-commitment-validator.py \\
        --print-ledger path/to/ledger.jsonl

Dependencies: standard library only (json, hashlib, argparse, uuid, datetime)
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


# ─────────────────────────────────────────────────────────────
# Hash Utilities
# ─────────────────────────────────────────────────────────────

def canonical_json(record: dict[str, Any]) -> bytes:
    """Canonical JSON: keys sorted, no whitespace, UTF-8."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_record(record: dict[str, Any]) -> str:
    """Compute SHA-256 of a canonical CTL record."""
    return sha256_hex(canonical_json(record))


def hash_file(path: Path) -> str:
    """Compute SHA-256 of a file's contents."""
    data = path.read_bytes()
    return sha256_hex(data)


def canonical_file_hash(path: Path) -> str:
    """
    Compute SHA-256 of the canonical JSON representation of a JSON file.
    This matches the hash that would be stored in a CommitmentRecord.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return sha256_hex(canonical_json(data))


# ─────────────────────────────────────────────────────────────
# Ledger I/O
# ─────────────────────────────────────────────────────────────

def load_ledger(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL ledger file (one JSON record per line)."""
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"ERROR: Invalid JSON on line {line_no}: {e}", file=sys.stderr)
                sys.exit(1)
    return records


def append_record(path: Path, record: dict[str, Any]) -> None:
    """Append a single record to a JSONL ledger file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        f.write("\n")


# ─────────────────────────────────────────────────────────────
# Chain Verification
# ─────────────────────────────────────────────────────────────

def verify_chain(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Verify the hash chain integrity of a sequence of CTL records.

    Returns a result dict with:
        intact: bool
        records_checked: int
        first_broken_id: str | None
        first_broken_index: int | None
        error: str | None
    """
    if not records:
        return {"intact": True, "records_checked": 0, "first_broken_id": None,
                "first_broken_index": None, "error": None}

    # First record must have prev_record_hash == "genesis"
    first = records[0]
    if first.get("prev_record_hash") != "genesis":
        return {
            "intact": False,
            "records_checked": 1,
            "first_broken_id": first.get("record_id"),
            "first_broken_index": 0,
            "error": f"First record must have prev_record_hash='genesis', got '{first.get('prev_record_hash')}'",
        }

    for i in range(1, len(records)):
        prev_record = records[i - 1]
        curr_record = records[i]
        expected_hash = hash_record(prev_record)
        actual_hash = curr_record.get("prev_record_hash", "")
        if actual_hash != expected_hash:
            return {
                "intact": False,
                "records_checked": i + 1,
                "first_broken_id": curr_record.get("record_id"),
                "first_broken_index": i,
                "error": (
                    f"Hash mismatch at record index {i} (id={curr_record.get('record_id')!r}): "
                    f"expected {expected_hash!r}, got {actual_hash!r}"
                ),
            }

    return {
        "intact": True,
        "records_checked": len(records),
        "first_broken_id": None,
        "first_broken_index": None,
        "error": None,
    }


# ─────────────────────────────────────────────────────────────
# Commitment
# ─────────────────────────────────────────────────────────────

def build_commitment_record(
    subject_path: Path,
    actor_id: str,
    commitment_type: str,
    prev_record_hash: str,
    summary: str | None = None,
) -> dict[str, Any]:
    """
    Build a CommitmentRecord for a domain pack or artifact file.
    """
    subject_hash = canonical_file_hash(subject_path)
    with open(subject_path, encoding="utf-8") as f:
        data = json.load(f)

    subject_id = data.get("id", str(subject_path))
    subject_version = data.get("version", None)
    auto_summary = f"Committed {subject_path.name} v{subject_version} hash={subject_hash[:12]}..."

    record: dict[str, Any] = {
        "record_type": "CommitmentRecord",
        "record_id": str(uuid.uuid4()),
        "prev_record_hash": prev_record_hash,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "actor_id": actor_id,
        "actor_role": "domain_authority",
        "commitment_type": commitment_type,
        "subject_id": subject_id,
        "subject_version": subject_version,
        "subject_hash": subject_hash,
        "summary": summary or auto_summary,
        "references": [],
        "metadata": {},
    }
    return record


# ─────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────

def cmd_verify_chain(args: argparse.Namespace) -> int:
    ledger_path = Path(args.ledger)
    records = load_ledger(ledger_path)
    print(f"Loaded {len(records)} records from {ledger_path}")
    result = verify_chain(records)

    if result["intact"]:
        print(f"Chain integrity: INTACT ✓  ({result['records_checked']} records verified)")
        return 0
    else:
        print(f"Chain integrity: BROKEN ✗", file=sys.stderr)
        print(f"  First broken at index {result['first_broken_index']}, "
              f"record_id={result['first_broken_id']!r}", file=sys.stderr)
        print(f"  Error: {result['error']}", file=sys.stderr)
        return 1


def cmd_verify_session(args: argparse.Namespace) -> int:
    ledger_path = Path(args.ledger)
    session_id = args.verify_session
    all_records = load_ledger(ledger_path)
    session_records = [r for r in all_records if r.get("session_id") == session_id]

    if not session_records:
        print(f"No records found for session_id={session_id!r}", file=sys.stderr)
        return 1

    # Verify the global chain first, then report session records
    global_result = verify_chain(all_records)
    print(f"Global chain: {'INTACT ✓' if global_result['intact'] else 'BROKEN ✗'}")
    print(f"Session {session_id!r}: {len(session_records)} records")
    for r in session_records:
        print(f"  [{r.get('record_type', '?')}] {r.get('record_id', '?')} "
              f"@ {r.get('timestamp_utc', '?')}")
    return 0 if global_result["intact"] else 1


def cmd_commit(args: argparse.Namespace) -> int:
    subject_path = Path(args.commit)
    ledger_path = Path(args.ledger)
    actor_id = args.actor_id

    if not subject_path.exists():
        print(f"ERROR: Subject file not found: {subject_path}", file=sys.stderr)
        return 1

    # Get prev_record_hash
    records = load_ledger(ledger_path)
    if records:
        prev_hash = hash_record(records[-1])
    else:
        prev_hash = "genesis"

    commitment_type = args.commitment_type or "domain_pack_activation"
    record = build_commitment_record(
        subject_path=subject_path,
        actor_id=actor_id,
        commitment_type=commitment_type,
        prev_record_hash=prev_hash,
        summary=args.summary,
    )

    append_record(ledger_path, record)
    print(f"Committed: {subject_path.name}")
    print(f"  record_id:    {record['record_id']}")
    print(f"  subject_hash: {record['subject_hash']}")
    print(f"  ledger:       {ledger_path}")
    return 0


def cmd_print_ledger(args: argparse.Namespace) -> int:
    ledger_path = Path(args.print_ledger)
    records = load_ledger(ledger_path)
    if not records:
        print(f"Ledger is empty or does not exist: {ledger_path}")
        return 0

    print(f"Ledger: {ledger_path}  ({len(records)} records)")
    print("─" * 70)
    for i, r in enumerate(records):
        print(f"[{i:04d}] {r.get('record_type', '?')} | {r.get('record_id', '?')}")
        print(f"       ts={r.get('timestamp_utc', '?')}")
        if r.get("record_type") == "CommitmentRecord":
            print(f"       actor={r.get('actor_id', '?')}  type={r.get('commitment_type', '?')}")
            print(f"       subject={r.get('subject_id', '?')}  ver={r.get('subject_version', '?')}")
        elif r.get("record_type") == "TraceEvent":
            print(f"       session={r.get('session_id', '?')}  event={r.get('event_type', '?')}")
            print(f"       decision={r.get('decision', '?')!r}")
        elif r.get("record_type") == "EscalationRecord":
            print(f"       session={r.get('session_id', '?')}  status={r.get('status', '?')}")
            print(f"       trigger={r.get('trigger', '?')!r}")
        print()
    return 0


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project Lumina CTL hash chain validator and commitment tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--verify-chain",
        metavar="LEDGER",
        help="Path to the JSONL ledger file. Verifies full hash chain.",
    )
    group.add_argument(
        "--verify-session",
        metavar="SESSION_ID",
        help="Session UUID to verify. Requires --ledger.",
    )
    group.add_argument(
        "--commit",
        metavar="JSON_FILE",
        help="Path to the artifact JSON file to commit. Requires --actor-id and --ledger.",
    )
    group.add_argument(
        "--print-ledger",
        metavar="LEDGER",
        help="Path to the JSONL ledger file. Prints records in human-readable form.",
    )

    parser.add_argument("--ledger", metavar="LEDGER", help="Path to the JSONL ledger file.")
    parser.add_argument("--actor-id", metavar="ID", help="Pseudonymous actor ID (for --commit).")
    parser.add_argument(
        "--commitment-type",
        metavar="TYPE",
        default="domain_pack_activation",
        help="CommitmentRecord type (default: domain_pack_activation).",
    )
    parser.add_argument("--summary", metavar="TEXT", help="Human-readable summary (for --commit).")

    args = parser.parse_args()

    if args.verify_chain:
        args.ledger = args.verify_chain
        sys.exit(cmd_verify_chain(args))
    elif args.verify_session:
        if not args.ledger:
            parser.error("--verify-session requires --ledger")
        sys.exit(cmd_verify_session(args))
    elif args.commit:
        if not args.ledger:
            parser.error("--commit requires --ledger")
        if not args.actor_id:
            parser.error("--commit requires --actor-id")
        sys.exit(cmd_commit(args))
    elif args.print_ledger:
        args.ledger = args.print_ledger
        sys.exit(cmd_print_ledger(args))


if __name__ == "__main__":
    main()
