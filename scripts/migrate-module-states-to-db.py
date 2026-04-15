#!/usr/bin/env python3
"""Migrate per-module state from profile YAML files to the persistence layer.

Walks ``data/profiles/*/education.yaml`` and extracts each entry in
``profile["modules"]``, writing it via ``PersistenceAdapter.save_module_state``.

Usage:
    python scripts/migrate-module-states-to-db.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate module states from profile YAML to DB.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be migrated without writing.")
    args = parser.parse_args()

    from lumina.core.yaml_loader import load_yaml

    profiles_dir = REPO_ROOT / "data" / "profiles"
    if not profiles_dir.is_dir():
        print(f"No profiles directory found at {profiles_dir}")
        return

    migrated = 0
    skipped = 0

    # Lazy-init persistence only if not dry-run
    persistence = None
    if not args.dry_run:
        from lumina.core import config as _cfg
        _cfg.bootstrap()
        persistence = _cfg.PERSISTENCE

    for user_dir in sorted(profiles_dir.iterdir()):
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        for profile_path in sorted(user_dir.glob("*.yaml")):
            try:
                profile = load_yaml(str(profile_path))
            except Exception as exc:
                print(f"  SKIP {profile_path}: {exc}")
                skipped += 1
                continue
            modules = profile.get("modules")
            if not isinstance(modules, dict) or not modules:
                continue
            for module_key, state in modules.items():
                if not isinstance(state, dict):
                    continue
                if args.dry_run:
                    print(f"  [DRY-RUN] {user_id} / {module_key} ({len(state)} keys)")
                else:
                    persistence.save_module_state(user_id, module_key, state)
                    print(f"  MIGRATED {user_id} / {module_key} ({len(state)} keys)")
                migrated += 1

    action = "would migrate" if args.dry_run else "migrated"
    print(f"\nDone: {action} {migrated} module-state entries, skipped {skipped} files.")


if __name__ == "__main__":
    main()
