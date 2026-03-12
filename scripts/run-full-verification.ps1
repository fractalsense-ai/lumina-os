param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [switch]$SkipOrchestratorDemo,
    [switch]$SkipFrontend,
    [switch]$SkipApiScenarios
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
}

function Assert-Command {
    param(
        [string]$Name,
        [string]$Hint
    )

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "Required command '$Name' not found. $Hint"
    }
}

function Test-ApiHealth {
    param([string]$BaseUrl)

    try {
        $health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/health" -TimeoutSec 2
        return $health.status -eq "ok"
    }
    catch {
        return $false
    }
}

function Wait-ApiHealth {
    param(
        [string]$BaseUrl,
        [int]$TimeoutSec = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-ApiHealth -BaseUrl $BaseUrl) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    return $false
}

Write-Section "Environment"
if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found at: $PythonExe"
}
Write-Host "Python: $PythonExe"

Write-Section "Secret Hygiene"
& "reference-implementations/check-local-secret-hygiene.ps1"
if ($LASTEXITCODE -ne 0) {
    throw "check-local-secret-hygiene.ps1 failed"
}

if (-not $SkipFrontend) {
    Assert-Command -Name "npm.cmd" -Hint "Install Node.js and ensure npm is in PATH."
    Write-Host "npm: available"
}

Write-Section "Repo Integrity"
& $PythonExe "reference-implementations/verify-repo-integrity.py"
if ($LASTEXITCODE -ne 0) {
    throw "verify-repo-integrity.py failed"
}

Write-Section "Manifest Integrity"
& $PythonExe -m lumina.systools.manifest_integrity check
if ($LASTEXITCODE -ne 0) {
    throw "Manifest integrity check failed (hash mismatch detected in docs/MANIFEST.yaml)"
}

if (-not $SkipOrchestratorDemo) {
    Write-Section "Orchestrator Demo"
    & $PythonExe "reference-implementations/dsa-orchestrator-demo.py"
    if ($LASTEXITCODE -ne 0) {
        throw "dsa-orchestrator-demo.py failed"
    }
}

if (-not $SkipFrontend) {
    Write-Section "Front-End Build"
    Push-Location "front-end"
    try {
        npm.cmd install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed"
        }

        npm.cmd run build
        if ($LASTEXITCODE -ne 0) {
            throw "npm run build failed"
        }
    }
    finally {
        Pop-Location
    }
}

if (-not $SkipApiScenarios) {
    Write-Section "Pre-Integration Scenarios"

    $apiProcess = $null
    $apiStdoutLog = $null
    $apiStderrLog = $null
    $startedApiServer = $false
    $previousLuminaPort = $env:LUMINA_PORT
    $previousRuntimeConfigPath = $env:LUMINA_RUNTIME_CONFIG_PATH
    $previousJwtSecret = $env:LUMINA_JWT_SECRET
    $previousCtlDir = $env:LUMINA_CTL_DIR
    $previousEnforcePolicyCommitment = $env:LUMINA_ENFORCE_POLICY_COMMITMENT

    try {
        if (-not (Test-ApiHealth -BaseUrl $ApiBaseUrl)) {
            $apiUri = [System.Uri]$ApiBaseUrl
            $apiPort = [int]$apiUri.Port

            Write-Host "API not reachable at $ApiBaseUrl. Starting local server on port $apiPort..."
            $env:LUMINA_PORT = "$apiPort"

            if ([string]::IsNullOrWhiteSpace($env:LUMINA_RUNTIME_CONFIG_PATH)) {
                $defaultRuntimeConfig = "domain-packs/education/runtime-config.yaml"
                Write-Host "LUMINA_RUNTIME_CONFIG_PATH not set; defaulting to '$defaultRuntimeConfig' for local API startup."
                $env:LUMINA_RUNTIME_CONFIG_PATH = $defaultRuntimeConfig
            }

            if ([string]::IsNullOrWhiteSpace($env:LUMINA_JWT_SECRET)) {
                $defaultJwtSecret = "lumina-local-verification-secret-32bytes-min"
                Write-Host "LUMINA_JWT_SECRET not set; using local verification secret for API startup."
                $env:LUMINA_JWT_SECRET = $defaultJwtSecret
            }

            if ([string]::IsNullOrWhiteSpace($env:LUMINA_CTL_DIR)) {
                $isolatedCtlDir = Join-Path ([System.IO.Path]::GetTempPath()) ("lumina-ctl-verify-" + [guid]::NewGuid().ToString("N"))
                Write-Host "LUMINA_CTL_DIR not set; using isolated CTL dir '$isolatedCtlDir' for local API startup."
                $env:LUMINA_CTL_DIR = $isolatedCtlDir
            }

            if ([string]::IsNullOrWhiteSpace($env:LUMINA_ENFORCE_POLICY_COMMITMENT)) {
                Write-Host "LUMINA_ENFORCE_POLICY_COMMITMENT not set; disabling policy commitment enforcement for local pre-integration scenarios."
                $env:LUMINA_ENFORCE_POLICY_COMMITMENT = "false"
            }

            $logToken = [guid]::NewGuid().ToString("N")
            $apiStdoutLog = Join-Path ([System.IO.Path]::GetTempPath()) ("lumina-api-" + $logToken + "-out.log")
            $apiStderrLog = Join-Path ([System.IO.Path]::GetTempPath()) ("lumina-api-" + $logToken + "-err.log")
            $apiProcess = Start-Process -FilePath $PythonExe -ArgumentList "reference-implementations/lumina-api-server.py" -WorkingDirectory $repoRoot -RedirectStandardOutput $apiStdoutLog -RedirectStandardError $apiStderrLog -PassThru
            $startedApiServer = $true

            if (-not (Wait-ApiHealth -BaseUrl $ApiBaseUrl -TimeoutSec 30)) {
                throw "API server did not become healthy at $ApiBaseUrl. Logs: $apiStdoutLog ; $apiStderrLog"
            }
        }

        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
        & "reference-implementations/run-preintegration-scenarios.ps1" -BaseUrl $ApiBaseUrl -PythonExe $PythonExe
        if ($LASTEXITCODE -ne 0) {
            throw "run-preintegration-scenarios.ps1 failed"
        }
    }
    finally {
        if ($null -eq $previousLuminaPort) {
            Remove-Item Env:LUMINA_PORT -ErrorAction SilentlyContinue
        }
        else {
            $env:LUMINA_PORT = $previousLuminaPort
        }

        if ($null -eq $previousRuntimeConfigPath) {
            Remove-Item Env:LUMINA_RUNTIME_CONFIG_PATH -ErrorAction SilentlyContinue
        }
        else {
            $env:LUMINA_RUNTIME_CONFIG_PATH = $previousRuntimeConfigPath
        }

        if ($null -eq $previousJwtSecret) {
            Remove-Item Env:LUMINA_JWT_SECRET -ErrorAction SilentlyContinue
        }
        else {
            $env:LUMINA_JWT_SECRET = $previousJwtSecret
        }

        if ($null -eq $previousCtlDir) {
            Remove-Item Env:LUMINA_CTL_DIR -ErrorAction SilentlyContinue
        }
        else {
            $env:LUMINA_CTL_DIR = $previousCtlDir
        }

        if ($null -eq $previousEnforcePolicyCommitment) {
            Remove-Item Env:LUMINA_ENFORCE_POLICY_COMMITMENT -ErrorAction SilentlyContinue
        }
        else {
            $env:LUMINA_ENFORCE_POLICY_COMMITMENT = $previousEnforcePolicyCommitment
        }

        if ($startedApiServer -and $apiProcess -and -not $apiProcess.HasExited) {
            Write-Host "Stopping API server (pid=$($apiProcess.Id))"
            Stop-Process -Id $apiProcess.Id -Force
        }
    }
}

Write-Section "Result"
Write-Host "All selected verification checks passed." -ForegroundColor Green
}
finally {
    Pop-Location
}
