#!/usr/bin/env bash
# check-local-secret-hygiene.sh — Verify that sensitive local files cannot be
# accidentally committed to git.
#
# Checks:
#   1. src/web/lib/openaikey.md is listed in .gitignore
#   2. The file is NOT tracked in the git index
#
# Usage:
#   bash scripts/check-local-secret-hygiene.sh
set -euo pipefail

SECRET_FILE="src/web/lib/openaikey.md"

# Ensure git is available
if ! command -v git &>/dev/null; then
    echo "ERROR: git command is required for secret hygiene checks." >&2
    exit 1
fi

if [ ! -f "$SECRET_FILE" ]; then
    echo "Secret file not found at '$SECRET_FILE' (skipping file-presence check)."
fi

# Must be ignored so local key notes cannot be committed by default.
if ! git check-ignore -q -- "$SECRET_FILE"; then
    echo "ERROR: Secret hygiene failed: '$SECRET_FILE' is not ignored. Add it to .gitignore." >&2
    exit 1
fi

# Must not already be tracked by git index.
tracked=$(git ls-files -- "$SECRET_FILE")
if [ -n "$tracked" ]; then
    echo "ERROR: Secret hygiene failed: '$SECRET_FILE' is tracked by git. Remove from index with: git rm --cached $SECRET_FILE" >&2
    exit 1
fi

echo "Secret hygiene checks passed for '$SECRET_FILE'."
