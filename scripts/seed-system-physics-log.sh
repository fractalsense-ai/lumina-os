#!/usr/bin/env bash
# seed-system-physics-log.sh — Seed the system-physics System Log with a
# CommitmentRecord for the active model-packs/system/cfg/system-physics.json.
#
# Computes the canonical JSON SHA-256 of model-packs/system/cfg/system-physics.json and appends
# a system_physics_activation CommitmentRecord to the system log ledger at
# <LUMINA_LOG_DIR>/system/system.jsonl.
#
# Safe to run multiple times: if the hash is already committed the script
# reports success without writing a duplicate record.
#
# Usage:
#   bash scripts/seed-system-physics-log.sh
#   bash scripts/seed-system-physics-log.sh --actor-id ci-pipeline --log-dir /tmp/lumina-log
#   PYTHON=python3.12 bash scripts/seed-system-physics-log.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

# ── Defaults ──────────────────────────────────────────────────────────────────
SYSTEM_PHYSICS_FILE="model-packs/system/cfg/system-physics.json"
ACTOR_ID="system-operator"
LOG_DIR=""

# ── Parse arguments ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --python-exe)  PYTHON="$2"; shift 2;;
        --physics-file) SYSTEM_PHYSICS_FILE="$2"; shift 2;;
        --actor-id)    ACTOR_ID="$2"; shift 2;;
        --log-dir)     LOG_DIR="$2"; shift 2;;
        *) echo "Unknown argument: $1" >&2; exit 1;;
    esac
done

# ── Activate venv ─────────────────────────────────────────────────────────────
if [ -f ".venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source ".venv/bin/activate"
fi

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" &>/dev/null; then
    cat >&2 <<EOF
Python executable not found: $PYTHON
  Create a virtual environment first:
    python3 -m venv .venv  (standard)
    uv venv                (uv)
  Then install dependencies:
    .venv/bin/pip install -e .[dev]
  Or supply a custom Python via --python-exe:
    bash scripts/seed-system-physics-log.sh --python-exe /usr/bin/python3.12
  See docs/1-commands/installation-and-packaging.md for full setup instructions.
EOF
    exit 1
fi

if [ ! -f "$SYSTEM_PHYSICS_FILE" ]; then
    echo "ERROR: system-physics.json not found at: $SYSTEM_PHYSICS_FILE" >&2
    exit 1
fi

# ── Resolve log directory ─────────────────────────────────────────────────────
if [ -z "$LOG_DIR" ]; then
    LOG_DIR="${LUMINA_LOG_DIR:-}"
fi
if [ -z "$LOG_DIR" ]; then
    LOG_DIR="${LUMINA_CTL_DIR:-}"
fi
if [ -z "$LOG_DIR" ]; then
    LOG_DIR="${TMPDIR:-/tmp}/lumina-log"
fi

LEDGER_FILE="$LOG_DIR/system/system.jsonl"

echo "System-physics file : $SYSTEM_PHYSICS_FILE"
echo "System Log directory       : $LOG_DIR"
echo "Actor ID            : $ACTOR_ID"
echo ""

# ── Run inline Python to compute hash, check existing, append ─────────────────
"$PYTHON" -c "
import hashlib, json, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

physics_path = Path('''$SYSTEM_PHYSICS_FILE''')
ledger_path  = Path('''$LEDGER_FILE''')
actor_id     = '''$ACTOR_ID'''

with open(physics_path, encoding='utf-8') as fh:
    data = json.load(fh)

subject_id      = data.get('id', str(physics_path))
subject_version = data.get('version', None)
canonical_bytes = json.dumps(data, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode('utf-8')
subject_hash    = hashlib.sha256(canonical_bytes).hexdigest()

print(f'subject_id:      {subject_id}')
print(f'subject_version: {subject_version}')
print(f'subject_hash:    {subject_hash}')

# Check if already committed
records = []
if ledger_path.exists():
    with open(ledger_path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

already_committed = any(
    r.get('record_type') == 'CommitmentRecord'
    and r.get('commitment_type') == 'system_physics_activation'
    and r.get('subject_hash') == subject_hash
    for r in records
)

if already_committed:
    print('Status: already committed [OK]')
    sys.exit(0)

# Compute prev_record_hash
def hash_record(rec):
    return hashlib.sha256(
        json.dumps(rec, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode('utf-8')
    ).hexdigest()

prev_hash = hash_record(records[-1]) if records else 'genesis'

new_record = {
    'record_type': 'CommitmentRecord',
    'record_id': str(uuid.uuid4()),
    'prev_record_hash': prev_hash,
    'timestamp_utc': datetime.now(timezone.utc).isoformat(),
    'actor_id': actor_id,
    'actor_role': 'system_operator',
    'commitment_type': 'system_physics_activation',
    'subject_id': subject_id,
    'subject_version': subject_version,
    'subject_hash': subject_hash,
    'summary': f'system-physics.json v{subject_version} activated hash={subject_hash[:12]}...',
    'references': [],
    'metadata': {},
}

ledger_path.parent.mkdir(parents=True, exist_ok=True)
with open(ledger_path, 'a', encoding='utf-8') as fh:
    fh.write(json.dumps(new_record, sort_keys=True, separators=(',',':'), ensure_ascii=False))
    fh.write('\n')

print(f'Status: committed [OK]')
print(f'record_id: {new_record[\"record_id\"]}')
print(f'ledger:    {ledger_path}')
"
