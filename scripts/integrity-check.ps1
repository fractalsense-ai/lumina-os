<#
.SYNOPSIS
    Verify SHA-256 hashes for all core artifacts listed in docs/MANIFEST.yaml.

.DESCRIPTION
    Runs the manifest integrity check tool (lumina.systools.manifest_integrity check).
    Exits 0 when all recorded hashes match the files on disk.
    PENDING and MISSING entries produce warnings but do not fail the check.
    Exits 1 if any MISMATCH (hash changed) is detected.

    Domain-pack artifact integrity is managed by the System Logs,
    not by this script.

.PARAMETER PythonExe
    Path to the Python executable. Defaults to .\.venv\Scripts\python.exe.

.EXAMPLE
    scripts\integrity-check.ps1
    scripts\integrity-check.ps1 -PythonExe "C:\Python312\python.exe"
#>
param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe"
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
        $msg += "    .\scripts\integrity-check.ps1 -PythonExe C:\Python312\python.exe`n"
        $msg += "  See docs/1-commands/installation-and-packaging.md for full setup instructions."
        throw $msg
    }

    & $PythonExe -m lumina.systools.manifest_integrity check
    if ($LASTEXITCODE -ne 0) {
        throw "Manifest integrity check failed - one or more SHA-256 mismatches detected. " +
              "Review changes and run scripts\manifest-regenerate.ps1 to update hashes."
    }
}
finally {
    Pop-Location
}
