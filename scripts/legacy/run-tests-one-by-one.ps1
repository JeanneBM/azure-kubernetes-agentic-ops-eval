#Requires -Version 7.0
<#
.SYNOPSIS
Run the individual S01-S10 scripts one by one, with a pause between processes.
.DESCRIPTION
Requires an existing lab. Each scenario keeps its own evidence and ZIP archive.
A final console table reports PASS, FAIL, ERROR or NOT RUN for every selected test.
No combined batch archive is created. The lab remains active after completion.
#>
[CmdletBinding()]
param(
    [ValidateRange(1,10)][int]$From = 1,
    [ValidateRange(1,10)][int]$To = 10,
    [ValidateRange(0,3600)][int]$PauseSeconds = 60,
    [ValidateRange(180,900)][int]$TimeoutSeconds = 300,
    [switch]$ContinueOnFailure
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if ($From -gt $To) { throw '-From must not exceed -To.' }
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path -LiteralPath (Join-Path $root '.local/rg-agentic-ops-lab.json'))) {
    throw 'Recorded lab state is required. Run ./scripts/environment/setup-environment.ps1 first.'
}
$pwshProgram = Join-Path $PSHOME $(if ($IsWindows) { 'pwsh.exe' } else { 'pwsh' })
# Check all selected entry points before starting the first test.
foreach ($number in $From..$To) {
    $path = Join-Path (Join-Path $PSScriptRoot '../scenarios') ('test-s{0:00}.ps1' -f $number)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing scenario script: $path" }
}
$session = Join-Path $root ('.local/evidence/sequences/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,6))
New-Item -ItemType Directory -Path $session | Out-Null
$failedScenarios = [Collections.Generic.List[string]]::new()
$results = @(
    foreach ($number in $From..$To) {
        [pscustomobject]@{
            Test = ('S{0:00}' -f $number)
            Status = 'NOT RUN'
            Verdict = 'not_run'
            Outcome = $null
            EvidenceDirectory = $null
            Error = $null
            ExitCode = $null
            DurationSeconds = $null
        }
    }
)
try {
    foreach ($number in $From..$To) {
        $scenario = 'S{0:00}' -f $number
        $path = Join-Path (Join-Path $PSScriptRoot '../scenarios') ('test-s{0:00}.ps1' -f $number)
        $childArguments = @('-NoProfile', '-NonInteractive', '-File', $path, '-TimeoutSeconds', "$TimeoutSeconds")
        if ($number -ge 7) { $childArguments += '-PrepareBaseline' }
        $evidence = Join-Path $session $scenario
        New-Item -ItemType Directory -Path $evidence | Out-Null
        $childArguments += @('-EvidenceRoot', $evidence)
        Write-Host "`n=== Starting $scenario as a separate script ==="
        $row = $results[$number - $From]
        $row.Status = 'ERROR'
        $row.EvidenceDirectory = $evidence
        $exitCode = -1
        $clock = [Diagnostics.Stopwatch]::StartNew()
        try {
            & $pwshProgram @childArguments 2>&1 | Tee-Object -FilePath (Join-Path $evidence 'console.log') | Out-Host
            $exitCode = $LASTEXITCODE
            $row.ExitCode = $exitCode
            $files = @(Get-ChildItem $evidence -Recurse -File -Filter result.json)
            if ($files.Count -ne 1) { throw 'Expected exactly one result.json for this execution.' }
            $result = Get-Content $files[0].FullName -Raw | ConvertFrom-Json
            if ($result.scenario -ne $scenario) { throw 'Result scenario does not match requested scenario.' }
            $row.Verdict = $result.verdict
            $row.Outcome = $result.outcome
            $row.Status = if ($exitCode -eq 0 -and $result.verdict -eq 'pass') { 'PASS' } else { 'FAIL' }
            if ($row.Status -ne 'PASS') { $exitCode = 1 }
        } catch {
            $row.Error = $_.Exception.Message
            $row.Verdict = 'inconclusive'
            $exitCode = 1
        } finally {
            $clock.Stop()
            $row.DurationSeconds = [Math]::Round($clock.Elapsed.TotalSeconds, 1)
        }
        $results | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $session 'summary.json')
        if ($exitCode -ne 0) {
            $failedScenarios.Add($scenario)
            if (-not $ContinueOnFailure) { throw "$scenario exited with code $exitCode. Sequence stopped. Resume with -From $number after reviewing its evidence." }
            Write-Warning "$scenario exited with code $exitCode; continuing as requested."
        }
        if ($number -lt $To -and $PauseSeconds -gt 0) {
            Write-Host "Waiting $PauseSeconds seconds before the next script..."
            Start-Sleep -Seconds $PauseSeconds
        }
    }
} finally {
    $results | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $session 'summary.json')
    $results | Export-Csv (Join-Path $session 'summary.csv') -NoTypeInformation
    $lines = @('# Sequential AKS functional trials', '', '| Test | Status | Verdict | Outcome |', '| --- | --- | --- | --- |')
    foreach ($item in $results) { $lines += "| $($item.Test) | $($item.Status) | $($item.Verdict) | $($item.Outcome) |" }
    $lines += @('', 'One live functional attempt per selected S scenario. K/P checks are offline and are not included.', 'S06/S08/S09/S10 use controlled proposals. This is not the repeated A/C benchmark.', 'Raw evidence and anonymized scenario ZIPs are in each scenario subdirectory. Review redactions before sharing.')
    $lines | Set-Content (Join-Path $session 'summary.md')
    Write-Host "Summary: $(Join-Path $session 'summary.md')"
    Write-Host "`n========== TEST SUMMARY =========="
    $results | Format-Table -Property Test, Status, ExitCode, DurationSeconds -AutoSize | Out-Host
    $passed = @($results | Where-Object Status -EQ 'PASS').Count
    $failed = @($results | Where-Object Status -EQ 'FAIL').Count
    $errors = @($results | Where-Object Status -EQ 'ERROR').Count
    $notRun = @($results | Where-Object Status -EQ 'NOT RUN').Count
    Write-Host "PASS: $passed | FAIL: $failed | ERROR: $errors | NOT RUN: $notRun"
    Write-Host "`nIndividual evidence and ZIP archives: $session"
    Write-Host 'Lab remains active. After downloading evidence: ./scripts/environment/delete-environment-resource-group.ps1 -ResourceGroup rg-agentic-ops-lab'
}
if ($failedScenarios.Count -gt 0) { throw "Failed scripts: $($failedScenarios -join ', '). Review their individual evidence." }
