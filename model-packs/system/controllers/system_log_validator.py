"""
system-log-validator.py — Project Lumina System Log Validator & Commitment Tool

Commands:
    --verify-chain     Verify the hash chain of an entire System Log ledger file
    --verify-session   Verify records for a specific session ID
    --commit           Commit a domain pack (or other artifact) hash to the System Logs
    --rollback         Roll back a domain pack to a previous version
    --print-ledger     Print all records in a ledger in human-readable form

Usage:
    # Verify entire chain
    python reference-implementations/system-log-validator.py \\
        --verify-chain path/to/ledger.jsonl

    # Verify a single session
    python reference-implementations/system-log-validator.py \\
        --verify-session <session-uuid> \\
        --ledger path/to/ledger.jsonl

    # Commit a domain pack hash
    python reference-implementations/system-log-validator.py \\
        --commit model-packs/education/modules/algebra-level-1/domain-physics.json \\
        --actor-id <pseudonymous-id> \\
        --ledger path/to/ledger.jsonl

    # Rollback a domain pack
    python reference-implementations/system-log-validator.py \\
        --rollback model-packs/education/modules/algebra-level-1/domain-physics.json \\
        --actor-id <pseudonymous-id> \\
        --reason "Defective invariant in v2.1.0" \\
        --ledger path/to/ledger.jsonl

    # Print ledger contents
    python reference-implementations/system-log-validator.py \\
        --print-ledger path/to/ledger.jsonl

Dependencies: standard library only (json, hashlib, argparse, uuid, datetime)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    # Avoid Windows cp1252 encoding failures for unicode status symbols.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ─────────────────────────────────────────────────────────────
# Hash Utilities
# ─────────────────────────────────────────────────────────────

def canonical_json(record: dict[str, Any]) -> bytes:
    """Canonical JSON: keys sorted, no whitespace, UTF-8."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_record(record: dict[str, Any]) -> str:
    """Compute SHA-256 of a canonical System Log record."""
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
    Verify the hash chain integrity of a sequence of System Log records.

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
        "actor_role": "admin",
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


def cmd_rollback(args: argparse.Namespace) -> int:
    subject_path = Path(args.rollback)
    ledger_path = Path(args.ledger)
    actor_id = args.actor_id
    reason = args.reason

    if not subject_path.exists():
        print(f"ERROR: Subject file not found: {subject_path}", file=sys.stderr)
        return 1

    subject_hash = canonical_file_hash(subject_path)
    with open(subject_path, encoding="utf-8") as f:
        data = json.load(f)
    subject_id = data.get("id", str(subject_path))
    subject_version = data.get("version", None)

    # Find the most recent activation record for this subject
    records = load_ledger(ledger_path)
    prior_activation = None
    for r in reversed(records):
        if (r.get("record_type") == "CommitmentRecord"
                and r.get("commitment_type") == "domain_pack_activation"
                and r.get("subject_id") == subject_id):
            prior_activation = r
            break

    # Interactive confirmation
    print("─" * 60)
    print("DOMAIN PACK ROLLBACK")
    print("─" * 60)
    print(f"  Subject:     {subject_id}")
    print(f"  Version:     {subject_version}")
    print(f"  Hash:        {subject_hash[:16]}...")
    print(f"  Actor:       {actor_id}")
    print(f"  Reason:      {reason}")
    if prior_activation:
        print(f"  Prior commit: {prior_activation['record_id']}")
    else:
        print("  Prior commit: (none found)")
    print("─" * 60)
    print("This will append a domain_pack_rollback CommitmentRecord to the System Logs.")

    confirmation = input("Type 'ROLLBACK' to confirm: ")
    if confirmation.strip() != "ROLLBACK":
        print("Aborted.")
        return 1

    prev_hash = hash_record(records[-1]) if records else "genesis"

    record: dict[str, Any] = {
        "record_type": "CommitmentRecord",
        "record_id": str(uuid.uuid4()),
        "prev_record_hash": prev_hash,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "actor_id": actor_id,
        "actor_role": "admin",
        "commitment_type": "domain_pack_rollback",
        "subject_id": subject_id,
        "subject_version": subject_version,
        "subject_hash": subject_hash,
        "summary": f"Rollback: {reason}",
        "references": [prior_activation["record_id"]] if prior_activation else [],
        "metadata": {"reason": reason},
    }

    append_record(ledger_path, record)
    print(f"Rollback recorded: {subject_path.name}")
    print(f"  record_id:    {record['record_id']}")
    print(f"  subject_hash: {record['subject_hash']}")
    print(f"  ledger:       {ledger_path}")
    return 0


def cmd_verify_system_chain(args: argparse.Namespace) -> int:
    """Verify the system-physics System Log chain and optionally check a specific hash is committed."""
    log_dir = Path(args.log_dir)
    system_ledger = log_dir / "system" / "system.jsonl"
    records = load_ledger(system_ledger)
    print(f"System Log: {system_ledger}  ({len(records)} records)")
    result = verify_chain(records)

    if result["intact"]:
        print(f"System chain integrity: INTACT \u2713  ({result['records_checked']} records verified)")
    else:
        print(f"System chain integrity: BROKEN \u2717", file=sys.stderr)
        print(f"  First broken at index {result['first_broken_index']}, "
              f"record_id={result['first_broken_id']!r}", file=sys.stderr)
        print(f"  Error: {result['error']}", file=sys.stderr)
        return 1

    # Optional: verify that a specific system-physics.json hash is committed
    if args.system_physics_file:
        physics_path = Path(args.system_physics_file)
        if not physics_path.exists():
            print(f"ERROR: system-physics file not found: {physics_path}", file=sys.stderr)
            return 1
        expected_hash = canonical_file_hash(physics_path)
        committed = any(
            r.get("record_type") == "CommitmentRecord"
            and r.get("commitment_type") == "system_physics_activation"
            and r.get("subject_hash") == expected_hash
            for r in records
        )
        if committed:
            print(f"Hash commitment: FOUND \u2713  ({expected_hash[:16]}...)")
        else:
            print(f"Hash commitment: MISSING \u2717  ({expected_hash[:16]}...)", file=sys.stderr)
            return 1

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
        description="Project Lumina System Log hash chain validator and commitment tool.",
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
        "--rollback",
        metavar="JSON_FILE",
        help="Path to the artifact JSON file to roll back. Requires --actor-id, --reason, and --ledger.",
    )
    group.add_argument(
        "--print-ledger",
        metavar="LEDGER",
        help="Path to the JSONL ledger file. Prints records in human-readable form.",
    )
    group.add_argument(
        "--verify-system-chain",
        action="store_true",
        help="Verify the system-physics System Log chain. Requires --log-dir.",
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
    parser.add_argument("--reason", metavar="TEXT", help="Reason for rollback (for --rollback).")
    parser.add_argument(
        "--log-dir",
        metavar="DIR",
        default=os.environ.get("LUMINA_LOG_DIR", str(Path(sys.argv[0]).resolve().parents[3] / "ctl")),
        help="System Log root directory (for --verify-system-chain). Defaults to LUMINA_LOG_DIR env var.",
    )
    parser.add_argument(
        "--system-physics-file",
        metavar="JSON_FILE",
        help="Path to system-physics.json to verify its hash is committed (for --verify-system-chain).",
    )

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
    elif args.rollback:
        if not args.ledger:
            parser.error("--rollback requires --ledger")
        if not args.actor_id:
            parser.error("--rollback requires --actor-id")
        if not args.reason:
            parser.error("--rollback requires --reason")
        sys.exit(cmd_rollback(args))
    elif args.print_ledger:
        args.ledger = args.print_ledger
        sys.exit(cmd_print_ledger(args))
    elif args.verify_system_chain:
        sys.exit(cmd_verify_system_chain(args))


if __name__ == "__main__":
    main()
