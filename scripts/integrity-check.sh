#!/usr/bin/env bash
# integrity-check.sh — Verify SHA-256 hashes for all core artifacts in docs/MANIFEST.yaml.
#
# Exits 0 when all recorded hashes match the files on disk.
# PENDING and MISSING entries produce warnings but do not fail the check.
# Exits 1 if any MISMATCH (hash changed) is detected.
#
# Domain-pack artifact integrity is managed by the Causal Trace Ledger (CTL),
# not by this script.
#
# Usage:
#   bash scripts/integrity-check.sh
#   PYTHON=python3.12 bash scripts/integrity-check.sh
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

exec "$PYTHON" -m lumina.systools.manifest_integrity check
