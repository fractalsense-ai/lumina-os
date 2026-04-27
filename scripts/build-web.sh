#!/usr/bin/env bash
# Build all frontend packages (domain packs first, then framework).
#
# Domain-pack web bundles are built before the framework so that build-time
# aliases resolve correctly. Each package runs `npm install` (if node_modules
# missing) then `npm run build`.
#
# Usage:
#   scripts/build-web.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PACKAGES=(
    "model-packs/education/web"
    "model-packs/system/web"
    "src/web"
)

FAILED=()

for pkg in "${PACKAGES[@]}"; do
    pkg_path="$REPO_ROOT/$pkg"
    if [ ! -f "$pkg_path/package.json" ]; then
        echo "WARNING: Skipping $pkg — no package.json"
        continue
    fi
    echo ""
    echo "── Building $pkg ──"
    pushd "$pkg_path" > /dev/null
    if [ ! -d "node_modules" ]; then
        echo "  npm install..."
        npm install --silent
    fi
    echo "  npm run build..."
    if npm run build; then
        echo "  OK"
    else
        echo "  FAILED"
        FAILED+=("$pkg")
    fi
    popd > /dev/null
done

if [ ${#FAILED[@]} -gt 0 ]; then
    echo ""
    echo "Failed packages:"
    for f in "${FAILED[@]}"; do
        echo "  - $f"
    done
    exit 1
fi

echo ""
echo "All packages built successfully."
