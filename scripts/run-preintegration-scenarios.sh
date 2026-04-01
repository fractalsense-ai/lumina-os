#!/usr/bin/env bash
# run-preintegration-scenarios.sh — Test critical API functionality against a
# live server: chat scenarios, escalation, provenance validation, and auth flows.
#
# Usage:
#   bash scripts/run-preintegration-scenarios.sh
#   bash scripts/run-preintegration-scenarios.sh --base-url http://localhost:9000
#   PYTHON=python3.12 bash scripts/run-preintegration-scenarios.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

# ── Defaults ──────────────────────────────────────────────────────────────────
BASE_URL="http://127.0.0.1:8000"

# ── Parse arguments ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --base-url)    BASE_URL="$2"; shift 2;;
        --python-exe)  PYTHON="$2"; shift 2;;
        *) echo "Unknown argument: $1" >&2; exit 1;;
    esac
done

# ── Activate venv ─────────────────────────────────────────────────────────────
if [ -f ".venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source ".venv/bin/activate"
fi

PYTHON="${PYTHON:-python3}"

# Require curl and jq
for cmd in curl jq; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: $cmd is required but not found." >&2
        exit 1
    fi
done

# ── Helpers ───────────────────────────────────────────────────────────────────

section() {
    echo ""
    echo "== $1 =="
}

assert_condition() {
    local condition="$1"
    local message="$2"
    if [ "$condition" != "true" ]; then
        echo "ASSERTION FAILED: $message" >&2
        exit 1
    fi
}

assert_is_sha256() {
    local value="$1"
    local label="$2"
    if ! echo "$value" | grep -qE '^[a-f0-9]{64}$'; then
        echo "ASSERTION FAILED: $label must be a 64-char lowercase SHA-256 hex digest (got '$value')" >&2
        exit 1
    fi
}

# Post a chat scenario and echo the JSON response
invoke_chat_scenario() {
    local session_id="$1"
    local message="$2"
    local turn_data="$3"

    local payload
    payload=$(jq -n \
        --arg sid "$session_id" \
        --arg msg "$message" \
        --argjson td "$turn_data" \
        '{session_id: $sid, message: $msg, deterministic_response: true, turn_data_override: $td}')

    curl -s -X POST "$BASE_URL/api/chat" \
        -H "Content-Type: application/json" \
        -d "$payload"
}

get_json_field() {
    echo "$1" | jq -r ".$2 // empty"
}

# ── Resolve System Log directory ──────────────────────────────────────────────
CTL_DIR="${LUMINA_LOG_DIR:-}"
if [ -z "$CTL_DIR" ]; then
    CTL_DIR="${TMPDIR:-/tmp}/lumina-log"
fi
mkdir -p "$CTL_DIR"

NO_ESC_SESSION="preint-noesc-$(head -c 4 /dev/urandom | od -A n -t x1 | tr -d ' \n')"
ESC_SESSION="preint-esc-$(head -c 4 /dev/urandom | od -A n -t x1 | tr -d ' \n')"
EXHAUST_SESSION="preint-exhaust-$(head -c 4 /dev/urandom | od -A n -t x1 | tr -d ' \n')"

NO_ESC_LEDGER="$CTL_DIR/session-$NO_ESC_SESSION.jsonl"
ESC_LEDGER="$CTL_DIR/session-$ESC_SESSION.jsonl"
EXHAUST_LEDGER="$CTL_DIR/session-$EXHAUST_SESSION.jsonl"

rm -f "$NO_ESC_LEDGER" "$ESC_LEDGER" "$EXHAUST_LEDGER"

# ── Health check ──────────────────────────────────────────────────────────────
section "Health Check"
health=$(curl -s "$BASE_URL/api/health")
status=$(get_json_field "$health" "status")
provider=$(get_json_field "$health" "provider")
echo "API status: $status provider=$provider"
assert_condition "$([ "$status" = "ok" ] && echo true || echo false)" "API health check failed"

# ── Scenario A: Stable Turn (No Escalation) ──────────────────────────────────
section "Scenario A: Stable Turn (No Escalation)"

STABLE_EVIDENCE='{
    "correctness": "correct",
    "hint_used": false,
    "response_latency_sec": 6.0,
    "frustration_marker_count": 0,
    "repeated_error": false,
    "off_task_ratio": 0.0,
    "equivalence_preserved": true,
    "illegal_operations": [],
    "substitution_check": true,
    "method_recognized": true,
    "step_count": 4
}'

stable=$(invoke_chat_scenario "$NO_ESC_SESSION" "I solved it and checked by substitution." "$STABLE_EVIDENCE")
echo "action=$(get_json_field "$stable" "action") prompt_type=$(get_json_field "$stable" "prompt_type") escalated=$(get_json_field "$stable" "escalated")"
escalated=$(get_json_field "$stable" "escalated")
assert_condition "$([ "$escalated" = "false" ] && echo true || echo false)" "Expected no escalation in stable scenario"

# ── Scenario B: Major Drift / Escalation ─────────────────────────────────────
section "Scenario B: Major Drift / Escalation"

ESCALATION_EVIDENCE='{
    "correctness": "incorrect",
    "hint_used": true,
    "response_latency_sec": 18.0,
    "frustration_marker_count": 3,
    "repeated_error": true,
    "off_task_ratio": 0.2,
    "equivalence_preserved": true,
    "illegal_operations": [],
    "substitution_check": true,
    "method_recognized": true,
    "step_count": 4
}'

escalated_resp=$(invoke_chat_scenario "$ESC_SESSION" "I keep messing this up and I am frustrated." "$ESCALATION_EVIDENCE")
echo "action=$(get_json_field "$escalated_resp" "action") prompt_type=$(get_json_field "$escalated_resp" "prompt_type") escalated=$(get_json_field "$escalated_resp" "escalated")"
escalated=$(get_json_field "$escalated_resp" "escalated")
assert_condition "$([ "$escalated" = "true" ] && echo true || echo false)" "Expected escalation in major drift scenario"

# ── Scenario C: Standing Order Exhaustion Escalation ──────────────────────────
section "Scenario C: Standing Order Exhaustion Escalation"

LOOP_EVIDENCE='{
    "correctness": "incorrect",
    "hint_used": false,
    "response_latency_sec": 6.0,
    "frustration_marker_count": 0,
    "repeated_error": true,
    "off_task_ratio": 0.0,
    "equivalence_preserved": false,
    "illegal_operations": [],
    "substitution_check": true,
    "method_recognized": true,
    "step_count": 2
}'

last_loop_resp=""
for turn in 1 2 3 4; do
    last_loop_resp=$(invoke_chat_scenario "$EXHAUST_SESSION" "loop turn $turn" "$LOOP_EVIDENCE")
    echo "turn=$turn action=$(get_json_field "$last_loop_resp" "action") escalated=$(get_json_field "$last_loop_resp" "escalated")"
done
escalated=$(get_json_field "$last_loop_resp" "escalated")
assert_condition "$([ "$escalated" = "true" ] && echo true || echo false)" "Expected escalation after standing-order max attempts are exhausted"

# ── System Log Ledger Presence ────────────────────────────────────────────────
section "System Log Ledger Presence"
assert_condition "$([ -f "$NO_ESC_LEDGER" ] && echo true || echo false)" "No-esc ledger file missing: $NO_ESC_LEDGER"
assert_condition "$([ -f "$ESC_LEDGER" ] && echo true || echo false)" "Esc ledger file missing: $ESC_LEDGER"
assert_condition "$([ -f "$EXHAUST_LEDGER" ] && echo true || echo false)" "Exhaust ledger file missing: $EXHAUST_LEDGER"
echo "No-escalation ledger: $NO_ESC_LEDGER"
echo "Escalation ledger:   $ESC_LEDGER"
echo "Exhaustion ledger:   $EXHAUST_LEDGER"

# ── Validate System Log Hash Chain ────────────────────────────────────────────
section "Validate System Log Hash Chain"

"$PYTHON" "reference-implementations/system-log-validator.py" --verify-chain "$NO_ESC_LEDGER"
"$PYTHON" "reference-implementations/system-log-validator.py" --verify-chain "$ESC_LEDGER"
"$PYTHON" "reference-implementations/system-log-validator.py" --verify-chain "$EXHAUST_LEDGER"

# ── Validate EscalationRecord Exists ──────────────────────────────────────────
section "Validate EscalationRecord Exists"

esc_count=$(jq -s '[.[] | select(.record_type == "EscalationRecord")] | length' "$ESC_LEDGER")
assert_condition "$([ "$esc_count" -ge 1 ] && echo true || echo false)" "Expected EscalationRecord in escalation ledger"
echo "EscalationRecord count: $esc_count"

exhaust_esc_count=$(jq -s '[.[] | select(.record_type == "EscalationRecord")] | length' "$EXHAUST_LEDGER")
assert_condition "$([ "$exhaust_esc_count" -ge 1 ] && echo true || echo false)" "Expected EscalationRecord in standing-order exhaustion ledger"
echo "Exhaustion EscalationRecord count: $exhaust_esc_count"

# ── Validate Provenance Metadata ──────────────────────────────────────────────
section "Validate Provenance Metadata"

validate_provenance_for_ledger() {
    local ledger="$1"
    local label="$2"
    local expect_escalation="$3"

    local required_runtime_keys=(
        domain_pack_id
        domain_pack_version
        domain_physics_hash
        global_prompt_hash
        domain_prompt_hash
        turn_interpretation_prompt_hash
        system_prompt_hash
        turn_data_hash
        prompt_contract_hash
    )

    local required_post_payload_keys=(
        tool_results_hash
        llm_payload_hash
        response_hash
    )

    local hash_keys=(
        domain_physics_hash
        global_prompt_hash
        domain_prompt_hash
        turn_interpretation_prompt_hash
        system_prompt_hash
        turn_data_hash
        prompt_contract_hash
        tool_results_hash
        llm_payload_hash
        response_hash
    )

    # Find TraceEvent with turn_data_hash in metadata
    local turn_trace
    turn_trace=$(jq -s '[.[] | select(.record_type == "TraceEvent" and .metadata.turn_data_hash != null)] | first' "$ledger")
    assert_condition "$([ "$turn_trace" != "null" ] && echo true || echo false)" "$label missing TraceEvent metadata with turn_data_hash"

    for key in "${required_runtime_keys[@]}"; do
        local value
        value=$(echo "$turn_trace" | jq -r ".metadata.$key // empty")
        assert_condition "$([ -n "$value" ] && echo true || echo false)" "$label missing provenance metadata key '$key'"
    done

    # Find TraceEvent with response_hash in metadata
    local post_trace
    post_trace=$(jq -s '[.[] | select(.record_type == "TraceEvent" and .metadata.response_hash != null)] | first' "$ledger")
    assert_condition "$([ "$post_trace" != "null" ] && echo true || echo false)" "$label missing post-payload provenance TraceEvent"

    for key in "${required_post_payload_keys[@]}"; do
        local value
        value=$(echo "$post_trace" | jq -r ".metadata.$key // empty")
        assert_condition "$([ -n "$value" ] && echo true || echo false)" "$label missing post-payload metadata key '$key'"
    done

    for key in "${hash_keys[@]}"; do
        local value
        value=$(echo "$post_trace" | jq -r ".metadata.$key // empty")
        if [ -z "$value" ]; then
            value=$(echo "$turn_trace" | jq -r ".metadata.$key // empty")
        fi
        assert_condition "$([ -n "$value" ] && echo true || echo false)" "$label missing hash field '$key' in provenance metadata"
        assert_is_sha256 "$value" "$label.$key"
    done

    if [ "$expect_escalation" = "true" ]; then
        local esc_record
        esc_record=$(jq -s '[.[] | select(.record_type == "EscalationRecord")] | first' "$ledger")
        assert_condition "$([ "$esc_record" != "null" ] && echo true || echo false)" "$label expected escalation record for provenance check"
        for key in domain_physics_hash turn_data_hash prompt_contract_hash; do
            local value
            value=$(echo "$esc_record" | jq -r ".metadata.$key // empty")
            assert_condition "$([ -n "$value" ] && echo true || echo false)" "$label EscalationRecord missing provenance key '$key'"
            assert_is_sha256 "$value" "$label.escalation.$key"
        done
    fi
}

validate_provenance_for_ledger "$NO_ESC_LEDGER" "stable" "false"
validate_provenance_for_ledger "$ESC_LEDGER" "major-drift" "true"
validate_provenance_for_ledger "$EXHAUST_LEDGER" "exhaustion" "true"
echo "Provenance metadata checks passed for all ledgers."

# ── Auth Flow Scenarios ───────────────────────────────────────────────────────
section "Auth: Register + Login + Token Flow"

REG_USERNAME="integ_root_$RANDOM"
REG_PASSWORD="TestPass123!"

reg_resp=$(curl -s -X POST "$BASE_URL/api/auth/register" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg u "$REG_USERNAME" --arg p "$REG_PASSWORD" '{username: $u, password: $p}')")

root_token=$(get_json_field "$reg_resp" "access_token")
reg_role=$(get_json_field "$reg_resp" "role")
assert_condition "$([ -n "$root_token" ] && echo true || echo false)" "Register should return access_token"
assert_condition "$([ "$reg_role" = "root" ] && echo true || echo false)" "First registered user should be root (bootstrap)"
echo "Bootstrap register passed (user promoted to root)."

# Login with the same user
login_resp=$(curl -s -X POST "$BASE_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg u "$REG_USERNAME" --arg p "$REG_PASSWORD" '{username: $u, password: $p}')")

login_token=$(get_json_field "$login_resp" "access_token")
assert_condition "$([ -n "$login_token" ] && echo true || echo false)" "Login should return access_token"
echo "Login passed."

# Access /api/auth/me with token
me_resp=$(curl -s -X GET "$BASE_URL/api/auth/me" \
    -H "Authorization: Bearer $root_token")
me_role=$(get_json_field "$me_resp" "role")
assert_condition "$([ "$me_role" = "root" ] && echo true || echo false)" "/auth/me should return role=root"
echo "Auth /me endpoint passed."

# Authenticated chat with token
auth_chat_body=$(jq -n '{
    message: "health check with auth",
    deterministic_response: true,
    turn_data_override: {
        correctness: "correct",
        frustration_marker_count: 0,
        step_count: 1,
        hint_used: false,
        repeated_error: false,
        off_task_ratio: 0.0,
        response_latency_sec: 3
    }
}')

auth_chat_resp=$(curl -s -X POST "$BASE_URL/api/chat" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $root_token" \
    -d "$auth_chat_body")
chat_response=$(get_json_field "$auth_chat_resp" "response")
assert_condition "$([ -n "$chat_response" ] && echo true || echo false)" "Authenticated chat should return response"
echo "Authenticated chat passed."

# ── Result ────────────────────────────────────────────────────────────────────
section "Result"
echo "Pre-integration scenarios passed."
echo "Session IDs: $NO_ESC_SESSION, $ESC_SESSION, $EXHAUST_SESSION"
