param(
	[string]$BaseUrl = "http://127.0.0.1:8000",
	[string]$PythonExe = ".\\.venv\\Scripts\\python.exe"
)

$ErrorActionPreference = "Stop"

function Write-Section {
	param([string]$Title)
	Write-Host ""
	Write-Host "== $Title ==" -ForegroundColor Cyan
}

function Invoke-ChatScenario {
	param(
		[string]$SessionId,
		[string]$Message,
		[hashtable]$TurnDataOverride
	)

	$payload = @{
		session_id = $SessionId
		message = $Message
		deterministic_response = $true
		turn_data_override = $TurnDataOverride
	} | ConvertTo-Json -Depth 6

	return Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/chat" -ContentType "application/json" -Body $payload
}

function Assert-Condition {
	param(
		[bool]$Condition,
		[string]$FailureMessage
	)

	if (-not $Condition) {
		throw $FailureMessage
	}
}

function Get-ObjectValue {
	param(
		[object]$Object,
		[string]$Key
	)

	if ($null -eq $Object) {
		return $null
	}

	if ($Object -is [hashtable]) {
		if ($Object.ContainsKey($Key)) {
			return $Object[$Key]
		}
		return $null
	}

	$prop = $Object.PSObject.Properties[$Key]
	if ($null -eq $prop) {
		return $null
	}
	return $prop.Value
}

function Assert-IsSha256Hex {
	param(
		[object]$Value,
		[string]$FieldLabel
	)

	$text = [string]$Value
	Assert-Condition ($text -match '^[a-f0-9]{64}$') "$FieldLabel must be a 64-char lowercase SHA-256 hex digest"
}

function Assert-ProvenanceForLedger {
	param(
		[array]$Records,
		[string]$LedgerLabel,
		[bool]$ExpectEscalation
	)

	$requiredRuntimeKeys = @(
		'domain_pack_id',
		'domain_pack_version',
		'domain_physics_hash',
		'global_prompt_hash',
		'domain_prompt_hash',
		'turn_interpretation_prompt_hash',
		'system_prompt_hash',
		'turn_data_hash',
		'prompt_contract_hash'
	)

	$requiredPostPayloadKeys = @(
		'tool_results_hash',
		'llm_payload_hash',
		'response_hash'
	)

	$hashKeys = @(
		'domain_physics_hash',
		'global_prompt_hash',
		'domain_prompt_hash',
		'turn_interpretation_prompt_hash',
		'system_prompt_hash',
		'turn_data_hash',
		'prompt_contract_hash',
		'tool_results_hash',
		'llm_payload_hash',
		'response_hash'
	)

	$traceRecords = @($Records | Where-Object { $_.record_type -eq 'TraceEvent' })
	Assert-Condition ($traceRecords.Count -ge 1) "$LedgerLabel must contain at least one TraceEvent"

	$turnTrace = $traceRecords | Where-Object {
		$md = Get-ObjectValue -Object $_ -Key 'metadata'
		$null -ne (Get-ObjectValue -Object $md -Key 'turn_data_hash')
	} | Select-Object -First 1
	Assert-Condition ($null -ne $turnTrace) "$LedgerLabel missing TraceEvent metadata with turn_data_hash"

	$turnMetadata = Get-ObjectValue -Object $turnTrace -Key 'metadata'
	foreach ($key in $requiredRuntimeKeys) {
		$value = Get-ObjectValue -Object $turnMetadata -Key $key
		Assert-Condition ($null -ne $value -and [string]$value -ne '') "$LedgerLabel missing provenance metadata key '$key'"
	}

	$postPayloadTrace = $traceRecords | Where-Object {
		$md = Get-ObjectValue -Object $_ -Key 'metadata'
		$null -ne (Get-ObjectValue -Object $md -Key 'response_hash')
	} | Select-Object -First 1
	Assert-Condition ($null -ne $postPayloadTrace) "$LedgerLabel missing post-payload provenance TraceEvent"

	$postPayloadMetadata = Get-ObjectValue -Object $postPayloadTrace -Key 'metadata'
	foreach ($key in $requiredPostPayloadKeys) {
		$value = Get-ObjectValue -Object $postPayloadMetadata -Key $key
		Assert-Condition ($null -ne $value -and [string]$value -ne '') "$LedgerLabel missing post-payload metadata key '$key'"
	}

	foreach ($key in $hashKeys) {
		$value = Get-ObjectValue -Object $postPayloadMetadata -Key $key
		if ($null -eq $value -or [string]$value -eq '') {
			$value = Get-ObjectValue -Object $turnMetadata -Key $key
		}
		Assert-Condition ($null -ne $value -and [string]$value -ne '') "$LedgerLabel missing hash field '$key' in provenance metadata"
		Assert-IsSha256Hex -Value $value -FieldLabel "$LedgerLabel.$key"
	}

	if ($ExpectEscalation) {
		$escalationRecord = $Records | Where-Object { $_.record_type -eq 'EscalationRecord' } | Select-Object -First 1
		Assert-Condition ($null -ne $escalationRecord) "$LedgerLabel expected escalation record for provenance check"
		$escalationMetadata = Get-ObjectValue -Object $escalationRecord -Key 'metadata'
		Assert-Condition ($null -ne $escalationMetadata) "$LedgerLabel EscalationRecord missing metadata"
		foreach ($key in @('domain_physics_hash', 'turn_data_hash', 'prompt_contract_hash')) {
			$value = Get-ObjectValue -Object $escalationMetadata -Key $key
			Assert-Condition ($null -ne $value -and [string]$value -ne '') "$LedgerLabel EscalationRecord missing provenance key '$key'"
			Assert-IsSha256Hex -Value $value -FieldLabel "$LedgerLabel.escalation.$key"
		}
	}
}

Write-Section "Health Check"
$health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/health"
Write-Host "API status: $($health.status) provider=$($health.provider)"
Assert-Condition ($health.status -eq "ok") "API health check failed"

$tempDir = [System.IO.Path]::GetTempPath()
$ctlDir = Join-Path $tempDir "lumina-ctl"
New-Item -ItemType Directory -Path $ctlDir -Force | Out-Null

$noEscSession = "preint-noesc-" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$escSession = "preint-esc-" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$exhaustSession = "preint-exhaust-" + ([guid]::NewGuid().ToString("N").Substring(0, 8))

$noEscLedger = Join-Path $ctlDir "session-$noEscSession.jsonl"
$escLedger = Join-Path $ctlDir "session-$escSession.jsonl"
$exhaustLedger = Join-Path $ctlDir "session-$exhaustSession.jsonl"

if (Test-Path $noEscLedger) { Remove-Item $noEscLedger -Force }
if (Test-Path $escLedger) { Remove-Item $escLedger -Force }
if (Test-Path $exhaustLedger) { Remove-Item $exhaustLedger -Force }

Write-Section "Scenario A: Stable Turn (No Escalation)"
$stableEvidence = @{
	correctness = "correct"
	hint_used = $false
	response_latency_sec = 6.0
	frustration_marker_count = 0
	repeated_error = $false
	off_task_ratio = 0.0
	equivalence_preserved = $true
	illegal_operations = @()
	substitution_check = $true
	method_recognized = $true
	step_count = 4
}

$stable = Invoke-ChatScenario -SessionId $noEscSession -Message "I solved it and checked by substitution." -TurnDataOverride $stableEvidence
Write-Host "action=$($stable.action) prompt_type=$($stable.prompt_type) escalated=$($stable.escalated)"
Assert-Condition (-not $stable.escalated) "Expected no escalation in stable scenario"

Write-Section "Scenario B: Major Drift / Escalation"
$escalationEvidence = @{
	correctness = "incorrect"
	hint_used = $true
	response_latency_sec = 18.0
	frustration_marker_count = 3
	repeated_error = $true
	off_task_ratio = 0.2
	equivalence_preserved = $true
	illegal_operations = @()
	substitution_check = $true
	method_recognized = $true
	step_count = 4
}

$escalated = Invoke-ChatScenario -SessionId $escSession -Message "I keep messing this up and I am frustrated." -TurnDataOverride $escalationEvidence
Write-Host "action=$($escalated.action) prompt_type=$($escalated.prompt_type) escalated=$($escalated.escalated)"
Assert-Condition ($escalated.escalated) "Expected escalation in major drift scenario"

Write-Section "Scenario C: Standing Order Exhaustion Escalation"
$loopEvidence = @{
	correctness = "incorrect"
	hint_used = $false
	response_latency_sec = 6.0
	frustration_marker_count = 0
	repeated_error = $true
	off_task_ratio = 0.0
	equivalence_preserved = $false
	illegal_operations = @()
	substitution_check = $true
	method_recognized = $true
	step_count = 2
}

$lastLoopResponse = $null
for ($turn = 1; $turn -le 4; $turn++) {
	$lastLoopResponse = Invoke-ChatScenario -SessionId $exhaustSession -Message "loop turn $turn" -TurnDataOverride $loopEvidence
	Write-Host "turn=$turn action=$($lastLoopResponse.action) escalated=$($lastLoopResponse.escalated)"
}
Assert-Condition ($lastLoopResponse.escalated) "Expected escalation after standing-order max attempts are exhausted"

Write-Section "CTL Ledger Presence"
Assert-Condition (Test-Path $noEscLedger) "No-esc ledger file missing: $noEscLedger"
Assert-Condition (Test-Path $escLedger) "Esc ledger file missing: $escLedger"
Assert-Condition (Test-Path $exhaustLedger) "Exhaust ledger file missing: $exhaustLedger"
Write-Host "No-escalation ledger: $noEscLedger"
Write-Host "Escalation ledger:   $escLedger"
Write-Host "Exhaustion ledger:   $exhaustLedger"

Write-Section "Validate CTL Hash Chain"
& $PythonExe "reference-implementations/ctl-commitment-validator.py" --verify-chain $noEscLedger
Assert-Condition ($LASTEXITCODE -eq 0) "CTL chain validation failed for non-escalation ledger"

& $PythonExe "reference-implementations/ctl-commitment-validator.py" --verify-chain $escLedger
Assert-Condition ($LASTEXITCODE -eq 0) "CTL chain validation failed for escalation ledger"

& $PythonExe "reference-implementations/ctl-commitment-validator.py" --verify-chain $exhaustLedger
Assert-Condition ($LASTEXITCODE -eq 0) "CTL chain validation failed for standing-order exhaustion ledger"

Write-Section "Validate EscalationRecord Exists"
$escRecords = Get-Content $escLedger | ForEach-Object { $_ | ConvertFrom-Json }
$escCount = @($escRecords | Where-Object { $_.record_type -eq "EscalationRecord" }).Count
Assert-Condition ($escCount -ge 1) "Expected EscalationRecord in escalation ledger"
Write-Host "EscalationRecord count: $escCount"

$exhaustRecords = Get-Content $exhaustLedger | ForEach-Object { $_ | ConvertFrom-Json }
$exhaustEscCount = @($exhaustRecords | Where-Object { $_.record_type -eq "EscalationRecord" }).Count
Assert-Condition ($exhaustEscCount -ge 1) "Expected EscalationRecord in standing-order exhaustion ledger"
Write-Host "Exhaustion EscalationRecord count: $exhaustEscCount"

Write-Section "Validate Provenance Metadata"
$stableRecords = Get-Content $noEscLedger | ForEach-Object { $_ | ConvertFrom-Json }
Assert-ProvenanceForLedger -Records $stableRecords -LedgerLabel "stable" -ExpectEscalation $false
Assert-ProvenanceForLedger -Records $escRecords -LedgerLabel "major-drift" -ExpectEscalation $true
Assert-ProvenanceForLedger -Records $exhaustRecords -LedgerLabel "exhaustion" -ExpectEscalation $true
Write-Host "Provenance metadata checks passed for all ledgers."

# ────────────────────────────────────────────────────────────
# Auth Flow Scenarios (against live API)
# ────────────────────────────────────────────────────────────

Write-Section "Auth: Register + Login + Token Flow"

# Register first user (bootstrap → root)
$regBody = @{
	username = "integ_root_$(Get-Random)"
	password = "TestPass123!"
} | ConvertTo-Json -Depth 4

$regResp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/register" -ContentType "application/json" -Body $regBody
Assert-Condition ($null -ne (Get-ObjectValue $regResp "access_token")) "Register should return access_token"
Assert-Condition ((Get-ObjectValue $regResp "role") -eq "root") "First registered user should be root (bootstrap)"
$rootToken = (Get-ObjectValue $regResp "access_token")
Write-Host "Bootstrap register passed (user promoted to root)."

# Login with the same user
$loginBody = ($regBody | ConvertFrom-Json)
$loginPayload = @{
	username = $loginBody.username
	password = $loginBody.password
} | ConvertTo-Json -Depth 4

$loginResp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/login" -ContentType "application/json" -Body $loginPayload
Assert-Condition ($null -ne (Get-ObjectValue $loginResp "access_token")) "Login should return access_token"
Write-Host "Login passed."

# Access /api/auth/me with token
$meHeaders = @{ Authorization = "Bearer $rootToken" }
$meResp = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/auth/me" -Headers $meHeaders
Assert-Condition ((Get-ObjectValue $meResp "role") -eq "root") "/auth/me should return role=root"
Write-Host "Auth /me endpoint passed."

# Authenticated chat with token
$authChatBody = @{
	message = "health check with auth"
	deterministic_response = $true
	turn_data_override = @{
		correctness = "correct"
		frustration_marker_count = 0
		step_count = 1
		hint_used = $false
		repeated_error = $false
		off_task_ratio = 0.0
		response_latency_sec = 3
	}
} | ConvertTo-Json -Depth 6
$authChatResp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/chat" -ContentType "application/json" -Body $authChatBody -Headers $meHeaders
Assert-Condition ($null -ne (Get-ObjectValue $authChatResp "response")) "Authenticated chat should return response"
Write-Host "Authenticated chat passed."

Write-Section "Result"
Write-Host "Pre-integration scenarios passed."
Write-Host "Session IDs: $noEscSession, $escSession, $exhaustSession"
