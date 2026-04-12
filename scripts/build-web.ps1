<#
.SYNOPSIS
    Build all frontend packages (domain packs first, then framework).

.DESCRIPTION
    Builds domain-pack web bundles (education, system) before the framework
    so that build-time aliases resolve correctly. Each package runs
    `npm install` (if node_modules missing) then `npm run build`.

.EXAMPLE
    scripts\build-web.ps1
#>

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

$packages = @(
    "domain-packs/education/web",
    "domain-packs/system/web",
    "src/web"
)

$failed = @()

foreach ($pkg in $packages) {
    $pkgPath = Join-Path $repoRoot $pkg
    if (-not (Test-Path (Join-Path $pkgPath "package.json"))) {
        Write-Warning "Skipping $pkg — no package.json"
        continue
    }
    Write-Host "`n── Building $pkg ──" -ForegroundColor Cyan
    Push-Location $pkgPath
    try {
        if (-not (Test-Path "node_modules")) {
            Write-Host "  npm install..."
            npm install --silent
            if ($LASTEXITCODE -ne 0) { throw "npm install failed for $pkg" }
        }
        Write-Host "  npm run build..."
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed for $pkg" }
        Write-Host "  OK" -ForegroundColor Green
    } catch {
        Write-Host "  FAILED: $_" -ForegroundColor Red
        $failed += $pkg
    } finally {
        Pop-Location
    }
}

Pop-Location

if ($failed.Count -gt 0) {
    Write-Host "`nFailed packages:" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

Write-Host "`nAll packages built successfully." -ForegroundColor Green
