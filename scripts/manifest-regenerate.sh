#!/usr/bin/env bash
# manifest-regenerate.sh — Recompute and rewrite SHA-256 hashes in docs/MANIFEST.yaml.
#
# Computes the SHA-256 hash of every artifact listed in docs/MANIFEST.yaml that
# exists on disk and rewrites the sha256: values in-place. The top-level
# last_updated: date is also updated to today.
#
# Formatting, comments, and all non-hash fields in docs/MANIFEST.yaml are preserved.
# Artifacts not found on disk receive a warning; their entries are left unchanged.
#
# Run this script after modifying any artifact listed in the manifest, after adding
# a new entry with sha256: pending, or whenever integrity-check.sh reports a MISMATCH.
#
# Domain-pack hashes are committed via the System Logs (lumina-system-log-validate), not this script.
#
# Usage:
#   bash scripts/manifest-regenerate.sh
#   PYTHON=python3.12 bash scripts/manifest-regenerate.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

# Activate the project virtualenv if present; otherwise fall back to system python3.
if [ -f ".venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source ".venv/bin/activate"
fi

PYTHON="${PYTHON:-python3}"

echo "Regenerating SHA-256 hashes in docs/MANIFEST.yaml..."
"$PYTHON" -m lumina.systools.manifest_integrity regen
echo "docs/MANIFEST.yaml updated. Run scripts/integrity-check.sh to verify."
