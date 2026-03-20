"""manifest_integrity — Project Lumina MANIFEST.yaml integrity check and regeneration.

Commands
--------
check  Verify SHA-256 hashes for all artifacts listed in docs/MANIFEST.yaml.
       Exits 0 if all recorded hashes match (pending/missing entries warn only).
       Exits 1 if any MISMATCH is detected.

regen  Recompute all SHA-256 hashes and rewrite docs/MANIFEST.yaml in-place.
       Preserves comments, formatting, and all non-hash fields.
       Also updates the top-level last_updated date to today.

Domain-pack artifact integrity is managed by the System Logs,
not by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import date
from pathlib import Path
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[3]

# ── Line-pattern constants ───────────────────────────────────
# Matches the start of an artifact entry:  - path: <value>
_PATH_LINE_RE = re.compile(r"^\s{2}-\s+path:\s+(.+)")
# Matches a sha256 field line inside an indented block.
# Group 1 = indentation+key+space prefix, group 2 = the hash/pending value.
_SHA256_LINE_RE = re.compile(r"^(\s+sha256:[ \t]+)(\S+)")
# Matches the top-level (unindented) last_updated field
_LAST_UPDATED_TOP_RE = re.compile(r"^(last_updated:[ \t]+)\S+")


# ─────────────────────────────────────────────────────────────
# Shared utilities
# ─────────────────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_artifacts(manifest_path: Path) -> list[dict[str, str]]:
    """Extract artifact path/sha256 pairs by scanning MANIFEST.yaml line-by-line.

    Uses direct line scanning rather than the YAML loader because the project's
    minimal yaml_loader does not handle nested block-mapping entries inside a
    sequence (list items with multiple indented key-value pairs).

    Returns a list of dicts with at minimum 'path' and 'sha256' keys.
    """
    lines = manifest_path.read_text(encoding="utf-8").splitlines()
    artifacts: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line in lines:
        m = _PATH_LINE_RE.match(line)
        if m:
            current = {"path": m.group(1).strip(), "sha256": "pending"}
            artifacts.append(current)
            continue

        if current is not None:
            m = _SHA256_LINE_RE.match(line)
            if m:
                current["sha256"] = m.group(2).strip()
                # Reset: each block has exactly one sha256 field.
                current = None
                continue

    return artifacts


# ─────────────────────────────────────────────────────────────
# check
# ─────────────────────────────────────────────────────────────

_OK = "OK"
_MISMATCH = "MISMATCH"
_PENDING = "PENDING"
_MISSING = "MISSING"


def check_manifest(repo_root: Path = REPO_ROOT) -> int:
    """Verify SHA-256 hashes for all artifacts in docs/MANIFEST.yaml.

    Returns 0 when all recorded hashes match the files on disk.
    PENDING and MISSING entries produce warnings but do not cause failure.
    Returns 1 if any MISMATCH is detected.
    """
    manifest_path = repo_root / "docs" / "MANIFEST.yaml"
    artifacts = _parse_artifacts(manifest_path)

    ok_count = mismatch_count = pending_count = missing_count = 0
    problem_lines: list[str] = []

    for entry in artifacts:
        rel_path = str(entry.get("path", "")).strip()
        if not rel_path:
            problem_lines.append("  [MISSING   ] <entry with no path field>")
            missing_count += 1
            continue

        recorded = str(entry.get("sha256", "")).strip()
        abs_path = repo_root / rel_path

        if not abs_path.exists():
            problem_lines.append(f"  [MISSING   ] {rel_path}  (file not found on disk)")
            missing_count += 1
            continue

        actual = _sha256_file(abs_path)

        if recorded == "pending":
            problem_lines.append(f"  [PENDING   ] {rel_path}")
            pending_count += 1
        elif recorded == actual:
            ok_count += 1
        else:
            problem_lines.append(
                f"  [MISMATCH  ] {rel_path}\n"
                f"               recorded={recorded[:16]}...  actual={actual[:16]}..."
            )
            mismatch_count += 1

    for line in problem_lines:
        print(line)
    if problem_lines:
        print()

    print(
        f"Manifest integrity: {ok_count} OK  |  "
        f"{pending_count} pending  |  "
        f"{missing_count} missing  |  "
        f"{mismatch_count} mismatch"
    )

    if mismatch_count:
        print(
            "\n[FAIL] One or more artifacts have SHA-256 mismatches — "
            "run 'lumina-manifest-regen' after reviewing changes.",
            file=sys.stderr,
        )
        return 1

    pending_hint = (
        " (pending entries present — run 'lumina-manifest-regen' to compute hashes)"
        if pending_count
        else ""
    )
    print(f"[PASS] Manifest integrity check passed{pending_hint}")
    return 0


# ─────────────────────────────────────────────────────────────
# regen
# ─────────────────────────────────────────────────────────────

def regen_manifest(repo_root: Path = REPO_ROOT) -> int:
    """Recompute all SHA-256 hashes and rewrite docs/MANIFEST.yaml in-place.

    Only sha256 values and the top-level last_updated date are changed.
    Comments, field order, and all other content are preserved.
    Artifacts not found on disk produce a warning; their entries are left unchanged.
    Returns 0 on success, 1 on error.
    """
    manifest_path = repo_root / "docs" / "MANIFEST.yaml"
    artifacts = _parse_artifacts(manifest_path)

    # Build {path → new_hash} for every artifact that exists on disk.
    hash_map: dict[str, str] = {}
    missing: list[str] = []
    for entry in artifacts:
        rel_path = str(entry.get("path", "")).strip()
        if not rel_path:
            continue
        abs_path = repo_root / rel_path
        if abs_path.exists():
            hash_map[rel_path] = _sha256_file(abs_path)
        else:
            missing.append(rel_path)

    if missing:
        print(f"[WARN] {len(missing)} artifact(s) not found on disk — sha256 entries left unchanged:")
        for m in missing:
            print(f"  - {m}")

    # Rewrite MANIFEST.yaml line-by-line, preserving all formatting and comments.
    raw_lines = manifest_path.read_text(encoding="utf-8").splitlines(keepends=True)
    out_lines: list[str] = []
    current_path: str | None = None
    today = date.today().isoformat()

    for line in raw_lines:
        # Top-level last_updated: (no leading whitespace — unindented)
        m = _LAST_UPDATED_TOP_RE.match(line)
        if m and not line[0].isspace():
            out_lines.append(m.group(1) + today + line[m.end():])
            continue

        # Start of a new artifact entry block
        m = _PATH_LINE_RE.match(line)
        if m:
            current_path = m.group(1).strip()
            out_lines.append(line)
            continue

        # sha256: line inside the current artifact block
        m = _SHA256_LINE_RE.match(line)
        if m and current_path is not None and current_path in hash_map:
            # m.group(1) = indentation + "sha256: "
            # line[m.end():] = whatever follows the old hash (typically "\n" or "\r\n")
            out_lines.append(m.group(1) + hash_map[current_path] + line[m.end():])
            current_path = None  # consumed; reset until the next path: line
            continue

        out_lines.append(line)

    manifest_path.write_text("".join(out_lines), encoding="utf-8")

    rel = manifest_path.relative_to(repo_root)
    print(f"[DONE] Regenerated {len(hash_map)} SHA-256 hash(es) in {rel}")
    if missing:
        print(f"[WARN] {len(missing)} artifact(s) were missing on disk — their hashes were not updated")
    return 0


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# API-compatible report functions (return dicts; no side-effects)
# ─────────────────────────────────────────────────────────────

def check_manifest_report(repo_root: Path = REPO_ROOT) -> dict:
    """Return a structured integrity report without printing or exiting.

    Used by the API layer (``GET /api/manifest/check``) to expose manifest
    health to authenticated callers.  The ``passed`` field mirrors the
    exit-0 / exit-1 logic of :func:`check_manifest`.
    """
    manifest_path = repo_root / "docs" / "MANIFEST.yaml"
    artifacts = _parse_artifacts(manifest_path)

    ok_count = mismatch_count = pending_count = missing_count = 0
    entries: list[dict] = []

    for entry in artifacts:
        rel_path = str(entry.get("path", "")).strip()
        if not rel_path:
            entries.append({"path": "", "status": _MISSING})
            missing_count += 1
            continue

        recorded = str(entry.get("sha256", "")).strip()
        abs_path = repo_root / rel_path

        if not abs_path.exists():
            entries.append({"path": rel_path, "status": _MISSING})
            missing_count += 1
            continue

        actual = _sha256_file(abs_path)

        if recorded == "pending":
            entries.append({"path": rel_path, "status": _PENDING})
            pending_count += 1
        elif recorded == actual:
            entries.append({"path": rel_path, "status": _OK})
            ok_count += 1
        else:
            entries.append({"path": rel_path, "status": _MISMATCH})
            mismatch_count += 1

    return {
        "passed": mismatch_count == 0,
        "ok_count": ok_count,
        "pending_count": pending_count,
        "missing_count": missing_count,
        "mismatch_count": mismatch_count,
        "entries": entries,
    }


def regen_manifest_report(repo_root: Path = REPO_ROOT) -> dict:
    """Recompute all SHA-256 hashes in-place and return a summary dict.

    Used by the API layer (``POST /api/manifest/regen``) to trigger a
    manifest refresh from an authenticated API call.
    """
    manifest_path = repo_root / "docs" / "MANIFEST.yaml"
    artifacts = _parse_artifacts(manifest_path)

    hash_map: dict[str, str] = {}
    missing: list[str] = []
    for entry in artifacts:
        rel_path = str(entry.get("path", "")).strip()
        if not rel_path:
            continue
        abs_path = repo_root / rel_path
        if abs_path.exists():
            hash_map[rel_path] = _sha256_file(abs_path)
        else:
            missing.append(rel_path)

    raw_lines = manifest_path.read_text(encoding="utf-8").splitlines(keepends=True)
    out_lines: list[str] = []
    current_path: str | None = None
    today = date.today().isoformat()

    for line in raw_lines:
        m = _LAST_UPDATED_TOP_RE.match(line)
        if m and not line[0].isspace():
            out_lines.append(m.group(1) + today + line[m.end():])
            continue

        m = _PATH_LINE_RE.match(line)
        if m:
            current_path = m.group(1).strip()
            out_lines.append(line)
            continue

        m = _SHA256_LINE_RE.match(line)
        if m and current_path is not None and current_path in hash_map:
            out_lines.append(m.group(1) + hash_map[current_path] + line[m.end():])
            current_path = None
            continue

        out_lines.append(line)

    manifest_path.write_text("".join(out_lines), encoding="utf-8")

    return {
        "updated_count": len(hash_map),
        "missing_paths": missing,
        "manifest_path": str(manifest_path.relative_to(repo_root)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="manifest_integrity",
        description="Check or regenerate SHA-256 hashes in docs/MANIFEST.yaml",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Verify recorded hashes; exit 1 on any MISMATCH")
    sub.add_parser(
        "regen",
        help="Recompute and rewrite all sha256 entries in docs/MANIFEST.yaml",
    )
    args = parser.parse_args(argv)

    if args.command == "check":
        return check_manifest()
    if args.command == "regen":
        return regen_manifest()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
