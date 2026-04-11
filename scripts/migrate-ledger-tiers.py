#!/usr/bin/env python3
"""Migrate legacy flat-file ledgers into the 3-tier directory structure.

Reads all ``session-*-*.jsonl`` and ``session-*.jsonl`` files under the
System Log root, classifies each record by tier (system / domain / module),
and writes it to the correct tier ledger file.  Original files are left in
place as backups — they are **not** deleted.

The script is idempotent: records already present in the target ledger
(matched by ``record_id``) are silently skipped.

Usage::

    python scripts/migrate-ledger-tiers.py [--log-dir <path>] [--dry-run]

If ``--log-dir`` is omitted the script falls back to the ``LUMINA_LOG_DIR``
environment variable, then to a default temp-directory path matching the
server convention.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

# ── Tier classification ──────────────────────────────────────

# Events / commit types that belong to the system tier.
_SYSTEM_COMMITMENT_TYPES = frozenset({
    "user_registered",
    "role_change",
    "user_deactivated",
    "token_revoked",
    "password_reset",
    "user_invited",
    "account_activated",
    "session_close",
    "daemon_proposal_resolution",
    "preference_update",
    "system_physics_activation",
})

_SYSTEM_EVENT_TYPES = frozenset({
    "routing_decision",
    "domain_switch",
    "admin_cmd_trace",
    "audit_requested",
    "manifest_regen",
    "hitl_staged",
    "hitl_reject",
    "hitl_accept",
    "hitl_modify",
    "hitl_resolved",
    "escalation_expired",
    "escalation_resolution",
    "ingestion_record",
})

# Events / commit types that belong to the domain tier.
_DOMAIN_COMMITMENT_TYPES = frozenset({
    "domain_pack_activation",
    "domain_role_assignment",
    "domain_role_revocation",
})


def _classify(record: dict) -> tuple[str, str | None]:
    """Return ``(tier, domain_id)`` for a record.

    *tier* is one of ``"system"``, ``"domain"``, ``"module"``.
    *domain_id* is set for domain/module-tier records.
    """
    rtype = record.get("record_type", "")
    ctype = record.get("commitment_type", "")
    etype = record.get("event_type", record.get("event", ""))

    # ── Explicit domain_id on the record ─────────────────────
    domain_id = record.get("domain_id") or record.get("domain_pack_id")

    # ── System tier ──────────────────────────────────────────
    if ctype in _SYSTEM_COMMITMENT_TYPES:
        return ("system", None)
    if etype in _SYSTEM_EVENT_TYPES:
        return ("system", None)
    if rtype == "EscalationRecord":
        return ("system", None)

    # ── Domain tier ──────────────────────────────────────────
    if ctype in _DOMAIN_COMMITMENT_TYPES:
        return ("domain", domain_id)
    if rtype == "CommitmentRecord" and domain_id:
        return ("domain", domain_id)

    # ── Fallback: system tier ────────────────────────────────
    return ("system", None)


# ── Helpers ──────────────────────────────────────────────────


def _load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _existing_ids(path: Path) -> set[str]:
    return {r.get("record_id", "") for r in _load_records(path)}


def _append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        fh.write("\n")


def _resolve_log_dir(cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg)
    env = os.environ.get("LUMINA_LOG_DIR")
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / "lumina-ctl"


# ── Main ─────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy ledgers to 3-tier structure")
    parser.add_argument("--log-dir", type=str, default=None, help="System Log root directory")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    args = parser.parse_args()

    log_dir = _resolve_log_dir(args.log_dir)
    if not log_dir.exists():
        print(f"Log directory does not exist: {log_dir}")
        sys.exit(1)

    # Discover legacy ledger files (flat session-*.jsonl at top level)
    legacy_files = sorted(log_dir.glob("session-*.jsonl"))
    if not legacy_files:
        print("No legacy ledger files found. Nothing to migrate.")
        return

    stats = {"system": 0, "domain": 0, "module": 0, "skipped": 0, "files": 0}

    for legacy_path in legacy_files:
        records = _load_records(legacy_path)
        if not records:
            continue
        stats["files"] += 1

        # Extract session_id from filename: session-{sid}.jsonl or session-{sid}-{domain}.jsonl
        stem = legacy_path.stem  # e.g. "session-admin-_admin" or "session-abc123"

        for record in records:
            rid = record.get("record_id", "")
            session_id = record.get("session_id", "admin")
            tier, domain_id = _classify(record)

            # Determine target path
            if tier == "system":
                target = log_dir / "system" / f"session-{session_id}.jsonl"
            elif tier == "domain" and domain_id:
                target = log_dir / "domains" / domain_id / "domain.jsonl"
            elif tier == "module" and domain_id:
                # Module tier needs module_id from the record
                module_id = record.get("module_id", "unknown")
                target = log_dir / "domains" / domain_id / "modules" / f"{module_id}.jsonl"
            else:
                # Unknown domain, put in system tier
                target = log_dir / "system" / f"session-{session_id}.jsonl"
                tier = "system"

            if args.dry_run:
                print(f"  [{tier:6s}] {rid[:12]:12s} → {target.relative_to(log_dir)}")
                stats[tier] += 1
                continue

            # Skip if already migrated
            if rid and rid in _existing_ids(target):
                stats["skipped"] += 1
                continue

            _append_record(target, record)
            stats[tier] += 1

    print(f"\nMigration {'(dry run) ' if args.dry_run else ''}complete.")
    print(f"  Legacy files scanned: {stats['files']}")
    print(f"  System tier records:  {stats['system']}")
    print(f"  Domain tier records:  {stats['domain']}")
    print(f"  Module tier records:  {stats['module']}")
    print(f"  Skipped (duplicate):  {stats['skipped']}")
    print(f"\nOriginal files in {log_dir} were NOT deleted.")


if __name__ == "__main__":
    main()
