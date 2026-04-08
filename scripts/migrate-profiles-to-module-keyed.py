#!/usr/bin/env python3
"""Migrate flat user profiles to two-tier module-keyed format.

Reads every user profile YAML under data/profiles/, adds a ``modules``
key if missing, and (if a ``domain_id`` is present) copies the existing
``learning_state`` or ``session_state`` into ``modules[domain_id]`` so
subsequent sessions use the module-keyed path.

Idempotent — profiles that already have a ``modules`` key with the
correct module entry are skipped.

Usage:
    python scripts/migrate-profiles-to-module-keyed.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def migrate_profile(path: Path, *, dry_run: bool = False) -> bool:
    """Migrate a single profile file.  Returns True if modified."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        return False

    domain_id = data.get("domain_id") or data.get("subject_domain_id") or ""
    modules = data.get("modules")
    if modules is None:
        data["modules"] = {}
        modules = data["modules"]

    modified = False

    # Copy flat learning_state into modules[domain_id] if not already there
    if domain_id and domain_id not in modules:
        ls = data.get("learning_state")
        ss = data.get("session_state")
        if isinstance(ls, dict) and ls:
            modules[domain_id] = dict(ls)
            modified = True
        elif isinstance(ss, dict) and ss:
            modules[domain_id] = dict(ss)
            modified = True

    # Ensure modules key exists even if nothing was copied
    if "modules" not in data:
        data["modules"] = {}
        modified = True

    if modified and not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(
                data, fh,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

    return modified


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing files")
    args = parser.parse_args()

    profiles_dir = Path(__file__).resolve().parent.parent / "data" / "profiles"
    if not profiles_dir.is_dir():
        print(f"No profiles directory found at {profiles_dir}", file=sys.stderr)
        sys.exit(1)

    migrated = 0
    skipped = 0
    for path in sorted(profiles_dir.rglob("*.yaml")):
        if migrate_profile(path, dry_run=args.dry_run):
            migrated += 1
            tag = "[DRY-RUN] " if args.dry_run else ""
            print(f"{tag}Migrated: {path}")
        else:
            skipped += 1

    print(f"\nDone. Migrated: {migrated}, Skipped (already current): {skipped}")


if __name__ == "__main__":
    main()
