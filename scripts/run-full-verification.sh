#!/usr/bin/env bash
# run-full-verification.sh — Master orchestration script running the
# comprehensive verification suite.
#
# Steps:
#   1. Secret hygiene check
#   2. Repo integrity (reference-implementations/verify-repo-integrity.py)
#   3. Manifest integrity (docs/MANIFEST.yaml hash verification)
#   4. Orchestrator demo (optional)
#   5. Front-end build (optional)
#   6. Pre-integration scenarios against live API (optional)
#
# Usage:
#   bash scripts/run-full-verification.sh
#   bash scripts/run-full-verification.sh --skip-frontend --skip-api-scenarios
#   PYTHON=python3.12 bash scripts/run-full-verification.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

# ── Defaults ──────────────────────────────────────────────────────────────────
API_BASE_URL="http://127.0.0.1:8000"
SKIP_ORCHESTRATOR_DEMO=false
SKIP_FRONTEND=false
SKIP_API_SCENARIOS=false

# ── Parse arguments ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --python-exe)             PYTHON="$2"; shift 2;;
        --api-base-url)           API_BASE_URL="$2"; shift 2;;
        --skip-orchestrator-demo) SKIP_ORCHESTRATOR_DEMO=true; shift;;
        --skip-frontend)          SKIP_FRONTEND=true; shift;;
        --skip-api-scenarios)     SKIP_API_SCENARIOS=true; shift;;
        *) echo "Unknown argument: $1" >&2; exit 1;;
    esac
done

# ── Activate venv ─────────────────────────────────────────────────────────────
if [ -f ".venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source ".venv/bin/activate"
fi

PYTHON="${PYTHON:-python3}"

# ── Helpers ───────────────────────────────────────────────────────────────────

section() {
    echo ""
    echo "== $1 =="
}

test_api_health() {
    local base_url="$1"
    local status
    status=$(curl -s --max-time 2 "$base_url/api/health" 2>/dev/null | jq -r '.status // empty' 2>/dev/null || true)
    [ "$status" = "ok" ]
}

wait_api_health() {
    local base_url="$1"
    local timeout="${2:-30}"
    local deadline=$((SECONDS + timeout))
    while [ $SECONDS -lt $deadline ]; do
        if test_api_health "$base_url"; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}

# ── Environment ───────────────────────────────────────────────────────────────
section "Environment"

if ! command -v "$PYTHON" &>/dev/null; then
    cat >&2 <<EOF
Python executable not found: $PYTHON
  Create a virtual environment first:
    python3 -m venv .venv  (standard)
    uv venv                (uv)
  Then install dependencies:
    .venv/bin/pip install -e .[dev]
  Or supply a custom Python via --python-exe:
    bash scripts/run-full-verification.sh --python-exe /usr/bin/python3.12
  See docs/1-commands/installation-and-packaging.md for full setup instructions.
EOF
    exit 1
fi
echo "Python: $PYTHON"

# ── Secret Hygiene ────────────────────────────────────────────────────────────
section "Secret Hygiene"
bash "$SCRIPT_DIR/check-local-secret-hygiene.sh"

if [ "$SKIP_FRONTEND" = "false" ]; then
    if ! command -v npm &>/dev/null; then
        echo "ERROR: npm is required for frontend build. Install Node.js and ensure npm is in PATH." >&2
        exit 1
    fi
    echo "npm: available"
fi

# ── Repo Integrity ────────────────────────────────────────────────────────────
section "Repo Integrity"
"$PYTHON" "reference-implementations/verify-repo-integrity.py"

# ── Manifest Integrity ────────────────────────────────────────────────────────
section "Manifest Integrity"
"$PYTHON" -m lumina.systools.manifest_integrity check

# ── Orchestrator Demo (optional) ──────────────────────────────────────────────
if [ "$SKIP_ORCHESTRATOR_DEMO" = "false" ]; then
    section "Orchestrator Demo"
    "$PYTHON" "reference-implementations/dsa-orchestrator-demo.py"
fi

# ── Front-End Build (optional) ────────────────────────────────────────────────
if [ "$SKIP_FRONTEND" = "false" ]; then
    section "Front-End Build"
    pushd "src/web" > /dev/null
    npm install
    npm run build
    popd > /dev/null
fi

# ── Pre-Integration Scenarios (optional) ──────────────────────────────────────
if [ "$SKIP_API_SCENARIOS" = "false" ]; then
    section "Pre-Integration Scenarios"

    API_PID=""
    API_STDOUT_LOG=""
    API_STDERR_LOG=""
    STARTED_API_SERVER=false

    # Save original env vars for restoration
    ORIG_LUMINA_PORT="${LUMINA_PORT:-}"
    ORIG_LUMINA_RUNTIME_CONFIG_PATH="${LUMINA_RUNTIME_CONFIG_PATH:-}"
    ORIG_LUMINA_JWT_SECRET="${LUMINA_JWT_SECRET:-}"
    ORIG_LUMINA_LOG_DIR="${LUMINA_LOG_DIR:-}"
    ORIG_LUMINA_ENFORCE_POLICY_COMMITMENT="${LUMINA_ENFORCE_POLICY_COMMITMENT:-}"

    cleanup_api() {
        if [ "$STARTED_API_SERVER" = "true" ] && [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then
            echo "Stopping API server (pid=$API_PID)"
            kill "$API_PID" 2>/dev/null || true
            wait "$API_PID" 2>/dev/null || true
        fi

        # Restore env vars
        if [ -n "$ORIG_LUMINA_PORT" ]; then export LUMINA_PORT="$ORIG_LUMINA_PORT"; else unset LUMINA_PORT 2>/dev/null || true; fi
        if [ -n "$ORIG_LUMINA_RUNTIME_CONFIG_PATH" ]; then export LUMINA_RUNTIME_CONFIG_PATH="$ORIG_LUMINA_RUNTIME_CONFIG_PATH"; else unset LUMINA_RUNTIME_CONFIG_PATH 2>/dev/null || true; fi
        if [ -n "$ORIG_LUMINA_JWT_SECRET" ]; then export LUMINA_JWT_SECRET="$ORIG_LUMINA_JWT_SECRET"; else unset LUMINA_JWT_SECRET 2>/dev/null || true; fi
        if [ -n "$ORIG_LUMINA_LOG_DIR" ]; then export LUMINA_LOG_DIR="$ORIG_LUMINA_LOG_DIR"; else unset LUMINA_LOG_DIR 2>/dev/null || true; fi
        if [ -n "$ORIG_LUMINA_ENFORCE_POLICY_COMMITMENT" ]; then export LUMINA_ENFORCE_POLICY_COMMITMENT="$ORIG_LUMINA_ENFORCE_POLICY_COMMITMENT"; else unset LUMINA_ENFORCE_POLICY_COMMITMENT 2>/dev/null || true; fi
    }
    trap cleanup_api EXIT

    # Seed system-physics System Log commitment before server startup
    echo "Seeding system-physics System Log commitment..."
    bash "$SCRIPT_DIR/seed-system-physics-log.sh"

    if ! test_api_health "$API_BASE_URL"; then
        # Extract port from URL
        API_PORT=$(echo "$API_BASE_URL" | sed -E 's|.*:([0-9]+).*|\1|')

        echo "API not reachable at $API_BASE_URL. Starting local server on port $API_PORT..."
        export LUMINA_PORT="$API_PORT"

        if [ -z "${LUMINA_RUNTIME_CONFIG_PATH:-}" ]; then
            DEFAULT_RUNTIME_CONFIG="domain-packs/education/runtime-config.yaml"
            echo "LUMINA_RUNTIME_CONFIG_PATH not set; defaulting to '$DEFAULT_RUNTIME_CONFIG' for local API startup."
            export LUMINA_RUNTIME_CONFIG_PATH="$DEFAULT_RUNTIME_CONFIG"
        fi

        if [ -z "${LUMINA_JWT_SECRET:-}" ]; then
            DEFAULT_JWT_SECRET="lumina-local-verification-secret-32bytes-min"
            echo "LUMINA_JWT_SECRET not set; using local verification secret for API startup."
            export LUMINA_JWT_SECRET="$DEFAULT_JWT_SECRET"
        fi

        if [ -z "${LUMINA_LOG_DIR:-}" ]; then
            ISOLATED_CTL_DIR="${TMPDIR:-/tmp}/lumina-log-verify-$(head -c 8 /dev/urandom | od -A n -t x1 | tr -d ' \n')"
            echo "LUMINA_LOG_DIR not set; using isolated System Log dir '$ISOLATED_CTL_DIR' for local API startup."
            export LUMINA_LOG_DIR="$ISOLATED_CTL_DIR"
        fi

        if [ -z "${LUMINA_ENFORCE_POLICY_COMMITMENT:-}" ]; then
            echo "LUMINA_ENFORCE_POLICY_COMMITMENT not set; disabling policy commitment enforcement for local pre-integration scenarios."
            export LUMINA_ENFORCE_POLICY_COMMITMENT="false"
        fi

        LOG_TOKEN=$(head -c 8 /dev/urandom | od -A n -t x1 | tr -d ' \n')
        API_STDOUT_LOG="${TMPDIR:-/tmp}/lumina-api-${LOG_TOKEN}-out.log"
        API_STDERR_LOG="${TMPDIR:-/tmp}/lumina-api-${LOG_TOKEN}-err.log"

        "$PYTHON" "reference-implementations/lumina-api-server.py" \
            > "$API_STDOUT_LOG" 2> "$API_STDERR_LOG" &
        API_PID=$!
        STARTED_API_SERVER=true

        if ! wait_api_health "$API_BASE_URL" 30; then
            echo "ERROR: API server did not become healthy at $API_BASE_URL. Logs: $API_STDOUT_LOG ; $API_STDERR_LOG" >&2
            exit 1
        fi
    fi

    bash "$SCRIPT_DIR/run-preintegration-scenarios.sh" --base-url "$API_BASE_URL" --python-exe "$PYTHON"
fi

# ── Result ────────────────────────────────────────────────────────────────────
section "Result"
echo "All selected verification checks passed."
