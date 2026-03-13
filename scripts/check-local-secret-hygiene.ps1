$SecretFile = "src/web/lib/openaikey.md"

$ErrorActionPreference = "Stop"

function Assert-GitCommand {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "git command is required for secret hygiene checks."
    }
}

Assert-GitCommand

if (-not (Test-Path $SecretFile)) {
    Write-Host "Secret file not found at '$SecretFile' (skipping file-presence check)." -ForegroundColor Yellow
}

# Must be ignored so local key notes cannot be committed by default.
git check-ignore -q -- "$SecretFile"
if ($LASTEXITCODE -ne 0) {
    throw "Secret hygiene failed: '$SecretFile' is not ignored. Add it to .gitignore."
}

# Must not already be tracked by git index.
$trackedEntries = git ls-files -- "$SecretFile"
if ($LASTEXITCODE -ne 0) {
    throw "Secret hygiene failed: git ls-files command did not complete successfully."
}

if ($trackedEntries) {
    throw "Secret hygiene failed: '$SecretFile' is tracked by git. Remove from index with: git rm --cached $SecretFile"
}

Write-Host "Secret hygiene checks passed for '$SecretFile'." -ForegroundColor Green
