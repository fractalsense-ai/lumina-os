<#
.SYNOPSIS
    Seeds the system-physics System Log with a CommitmentRecord for the active
    cfg/system-physics.json, enabling the runtime system-physics gate.

.DESCRIPTION
    Computes the canonical JSON SHA-256 of cfg/system-physics.json and
    appends a system_physics_activation CommitmentRecord to the system log
    ledger at <LUMINA_LOG_DIR>/system/system.jsonl.

    Safe to run multiple times: if the hash is already committed, the script
    reports success without writing a duplicate record.

.PARAMETER PythonExe
    Path to the Python executable to use (default: .\.venv\Scripts\python.exe).

.PARAMETER SystemPhysicsFile
    Path to the system-physics.json to commit
    (default: cfg/system-physics.json relative to the repo root).

.PARAMETER ActorId
    Pseudonymous actor ID to record in the CommitmentRecord
    (default: "system-operator").

.PARAMETER CtlDir
    System Log root directory. Defaults to LUMINA_LOG_DIR env var, then
    a temp directory matching the server default.

.EXAMPLE
    .\scripts\seed-system-physics-log.ps1

.EXAMPLE
    .\scripts\seed-system-physics-log.ps1 `
        -ActorId "ci-pipeline" `
        -CtlDir "C:\lumina-data\ctl"
#>
param(
    [string]$PythonExe        = ".\.venv\Scripts\python.exe",
    [string]$SystemPhysicsFile = "cfg\system-physics.json",
    [string]$ActorId           = "system-operator",
    [string]$CtlDir            = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    if (-not (Test-Path $PythonExe)) {
        $msg  = "Python executable not found at: $PythonExe`n"
        $msg += "  Create a virtual environment first:`n"
        $msg += "    python -m venv .venv  (standard)`n"
        $msg += "    uv venv               (uv)`n"
        $msg += "  Then install dependencies:`n"
        $msg += "    .\.venv\Scripts\pip install -e .[dev]`n"
        $msg += "  Or supply a custom Python via -PythonExe:`n"
        $msg += "    .\scripts\seed-system-physics-log.ps1 -PythonExe C:\Python312\python.exe`n"
        $msg += "  See docs/1-commands/installation-and-packaging.md for full setup instructions."
        throw $msg
    }
    if (-not (Test-Path $SystemPhysicsFile)) {
        throw "system-physics.json not found at: $SystemPhysicsFile"
    }

    # Resolve System Log directory
    if ([string]::IsNullOrWhiteSpace($CtlDir)) {
        $CtlDir = $env:LUMINA_LOG_DIR
    }
    if ([string]::IsNullOrWhiteSpace($CtlDir)) {
        $CtlDir = Join-Path ([System.IO.Path]::GetTempPath()) "lumina-log"
    }

    Write-Host "System-physics file : $SystemPhysicsFile"
    Write-Host "System Log directory       : $CtlDir"
    Write-Host "Actor ID            : $ActorId"
    Write-Host ""

    $ledgerDir  = Join-Path $CtlDir "system"
    $ledgerFile = Join-Path $ledgerDir "system.jsonl"

    # Python inline script: compute canonical hash, check for existing
    # commitment, append if absent.
    $pythonScript = @"
import hashlib, json, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

physics_path = Path(r'$($SystemPhysicsFile.Replace("'","\'"))')
ledger_path  = Path(r'$($ledgerFile.Replace("'","\'"))')

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
    'actor_id': '$ActorId',
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
"@

    & $PythonExe -c $pythonScript
    if ($LASTEXITCODE -ne 0) {
        throw "Seed script failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
