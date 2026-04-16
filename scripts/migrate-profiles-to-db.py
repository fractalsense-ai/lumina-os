#!/usr/bin/env python3
"""Migrate YAML profile files into the key-based persistence store.

Walks ``data/profiles/`` and ingests each profile YAML into the
persistence backend via ``save_profile(user_id, domain_key, data)``.

Handles two layouts:
  - **Hierarchical** (current): ``data/profiles/{user_id}/{domain_key}.yaml``
  - **Flat legacy**:            ``data/profiles/{user_id}.yaml``
    (treated as domain_key = ``"default"``)

Usage::

    python scripts/migrate-profiles-to-db.py               # live run
    python scripts/migrate-profiles-to-db.py --dry-run      # preview only
    python scripts/migrate-profiles-to-db.py --backend sqlite  # explicit backend
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure repo root is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("migrate-profiles")


def _load_yaml_file(path: Path) -> dict | None:
    """Load a YAML file, returning None on error."""
    try:
        import yaml  # type: ignore[import-untyped]

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, dict):
            return data
        log.warning("Skipped %s — not a dict (got %s)", path, type(data).__name__)
        return None
    except Exception as exc:
        log.error("Failed to load %s: %s", path, exc)
        return None


def _discover_profiles(profiles_dir: Path) -> list[tuple[str, str, Path]]:
    """Return a list of (user_id, domain_key, file_path) tuples."""
    results: list[tuple[str, str, Path]] = []
    if not profiles_dir.is_dir():
        log.warning("Profiles directory not found: %s", profiles_dir)
        return results

    for entry in sorted(profiles_dir.iterdir()):
        if entry.is_file() and entry.suffix == ".yaml":
            # Flat legacy: data/profiles/{user_id}.yaml
            user_id = entry.stem
            results.append((user_id, "default", entry))
        elif entry.is_dir():
            user_id = entry.name
            for profile_file in sorted(entry.glob("*.yaml")):
                domain_key = profile_file.stem
                results.append((user_id, domain_key, profile_file))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate profile YAMLs into key-based persistence store.")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be migrated without writing.")
    parser.add_argument("--backend", choices=["filesystem", "sqlite"], default=None,
                        help="Force a persistence backend (default: auto-detect from LUMINA_PERSISTENCE_BACKEND).")
    parser.add_argument("--profiles-dir", type=Path, default=_REPO_ROOT / "data" / "profiles",
                        help="Path to profiles directory.")
    args = parser.parse_args()

    if args.backend:
        os.environ["LUMINA_PERSISTENCE_BACKEND"] = args.backend

    profiles = _discover_profiles(args.profiles_dir)
    if not profiles:
        log.info("No profiles found in %s — nothing to migrate.", args.profiles_dir)
        return

    log.info("Discovered %d profile(s) to migrate.", len(profiles))

    if args.dry_run:
        for user_id, domain_key, path in profiles:
            log.info("[DRY-RUN] Would migrate: user=%s domain=%s from %s", user_id, domain_key, path)
        log.info("[DRY-RUN] Total: %d profile(s). No changes made.", len(profiles))
        return

    # Import persistence after env is set
    from lumina.api import config as _cfg

    migrated = 0
    skipped = 0
    errors = 0

    for user_id, domain_key, path in profiles:
        data = _load_yaml_file(path)
        if data is None:
            skipped += 1
            continue
        try:
            _cfg.PERSISTENCE.save_profile(user_id, domain_key, data)
            migrated += 1
            log.info("Migrated: user=%s domain=%s (%d keys)", user_id, domain_key, len(data))
        except Exception as exc:
            errors += 1
            log.error("Error migrating user=%s domain=%s: %s", user_id, domain_key, exc)

    log.info(
        "Migration complete: %d migrated, %d skipped, %d errors (of %d total).",
        migrated, skipped, errors, len(profiles),
    )
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
