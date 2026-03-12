<#
.SYNOPSIS
    Recompute and rewrite SHA-256 hashes in docs/MANIFEST.yaml.

.DESCRIPTION
    Runs the manifest regeneration tool (lumina.systools.manifest_integrity regen).
    Computes the SHA-256 hash of every artifact listed in docs/MANIFEST.yaml that
    exists on disk and rewrites the sha256: values in-place. The top-level
    last_updated: date is also updated to today.

    Formatting, comments, and all non-hash fields in docs/MANIFEST.yaml are preserved.
    Artifacts not found on disk receive a warning; their entries are left unchanged.

    Run this script after modifying any artifact listed in the manifest, after adding
    a new entry with sha256: pending, or whenever integrity-check.ps1 reports a MISMATCH.

    Domain-pack hashes are committed via the CTL (lumina-ctl-validate), not this script.

.PARAMETER PythonExe
    Path to the Python executable. Defaults to .\.venv\Scripts\python.exe.

.EXAMPLE
    scripts\manifest-regenerate.ps1
    scripts\manifest-regenerate.ps1 -PythonExe "C:\Python312\python.exe"
#>
param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    if (-not (Test-Path $PythonExe)) {
        throw "Python executable not found at: $PythonExe"
    }

    Write-Host "Regenerating SHA-256 hashes in docs/MANIFEST.yaml..." -ForegroundColor Cyan
    & $PythonExe -m lumina.systools.manifest_integrity regen
    if ($LASTEXITCODE -ne 0) {
        throw "Manifest regeneration failed. Check the output above for details."
    }
    Write-Host "docs/MANIFEST.yaml updated. Run scripts\integrity-check.ps1 to verify." -ForegroundColor Green
}
finally {
    Pop-Location
}
