#!/usr/bin/env python3
"""Backfill domain_roles from YAML profiles into the user persistence store.

Teachers (and other domain-role holders) may have ``domain_roles`` in their
profile YAML that was never synced to the user DB record.  This script
reads every profile, and for any that contain a non-empty ``domain_roles``
dict, calls ``persistence.update_user_domain_roles()`` so that subsequent
JWTs include the roles.

Usage::

    python scripts/backfill-domain-roles-to-db.py               # live run
    python scripts/backfill-domain-roles-to-db.py --dry-run      # preview only
    python scripts/backfill-domain-roles-to-db.py --backend sqlite
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill-domain-roles")


def _load_yaml(path: Path) -> dict | None:
    try:
        import yaml  # type: ignore[import-untyped]
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        log.error("Failed to load %s: %s", path, exc)
        return None


def _discover_profiles(profiles_dir: Path) -> list[tuple[str, Path]]:
    """Return (user_id, file_path) for every profile YAML."""
    results: list[tuple[str, Path]] = []
    if not profiles_dir.is_dir():
        return results
    for entry in sorted(profiles_dir.iterdir()):
        if entry.is_dir():
            for f in sorted(entry.glob("*.yaml")):
                results.append((entry.name, f))
        elif entry.suffix in (".yaml", ".yml"):
            results.append((entry.stem, entry))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--backend",
        choices=["filesystem", "sqlite"],
        default=None,
        help="Persistence backend (default: from LUMINA_PERSISTENCE_BACKEND env)",
    )
    args = parser.parse_args()

    profiles_dir = _REPO_ROOT / "data" / "profiles"
    profiles = _discover_profiles(profiles_dir)
    if not profiles:
        log.info("No profiles found in %s", profiles_dir)
        return

    # Initialise persistence
    if args.backend:
        import os
        os.environ["LUMINA_PERSISTENCE_BACKEND"] = args.backend

    from lumina.persistence.adapter import create_persistence
    persistence = create_persistence()

    synced = 0
    skipped = 0

    for user_id, path in profiles:
        data = _load_yaml(path)
        if data is None:
            skipped += 1
            continue

        domain_roles: dict[str, str] = data.get("domain_roles") or {}
        if not domain_roles:
            skipped += 1
            continue

        # Verify user exists
        user_rec = persistence.get_user(user_id)
        if user_rec is None:
            log.warning("User %s not found in DB — skipping", user_id)
            skipped += 1
            continue

        existing = dict(user_rec.get("domain_roles") or {})
        new_roles = {k: v for k, v in domain_roles.items() if k not in existing}
        if not new_roles:
            log.debug("User %s already up-to-date", user_id)
            skipped += 1
            continue

        if args.dry_run:
            log.info("[DRY-RUN] Would sync %s → %s", user_id, new_roles)
        else:
            persistence.update_user_domain_roles(user_id, new_roles)
            log.info("Synced %s → %s", user_id, new_roles)
        synced += 1

    log.info("Done: %d synced, %d skipped", synced, skipped)


if __name__ == "__main__":
    main()
