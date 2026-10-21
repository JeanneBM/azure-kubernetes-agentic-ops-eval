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
    $path = Join-Path $PSScriptRoot ('test-s{0:00}.ps1' -f $number)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing scenario script: $path" }
}
$failedScenarios = [Collections.Generic.List[string]]::new()
$results = @(
    foreach ($number in $From..$To) {
        [pscustomobject]@{
            Test = ('S{0:00}' -f $number)
            Status = 'NOT RUN'
            ExitCode = $null
            DurationSeconds = $null
        }
    }
)
try {
    foreach ($number in $From..$To) {
        $scenario = 'S{0:00}' -f $number
        $path = Join-Path $PSScriptRoot ('test-s{0:00}.ps1' -f $number)
        $childArguments = @('-NoProfile', '-NonInteractive', '-File', $path, '-TimeoutSeconds', "$TimeoutSeconds")
        if ($number -ge 7) { $childArguments += '-PrepareBaseline' }
        Write-Host "`n=== Starting $scenario as a separate script ==="
        $row = $results[$number - $From]
        $row.Status = 'ERROR'
        $clock = [Diagnostics.Stopwatch]::StartNew()
        try {
            & $pwshProgram @childArguments
            $exitCode = $LASTEXITCODE
            $row.ExitCode = $exitCode
            $row.Status = if ($exitCode -eq 0) { 'PASS' } else { 'FAIL' }
        } finally {
            $clock.Stop()
            $row.DurationSeconds = [Math]::Round($clock.Elapsed.TotalSeconds, 1)
        }
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
    Write-Host "`n========== TEST SUMMARY =========="
    $results | Format-Table -Property Test, Status, ExitCode, DurationSeconds -AutoSize | Out-Host
    $passed = @($results | Where-Object Status -EQ 'PASS').Count
    $failed = @($results | Where-Object Status -EQ 'FAIL').Count
    $errors = @($results | Where-Object Status -EQ 'ERROR').Count
    $notRun = @($results | Where-Object Status -EQ 'NOT RUN').Count
    Write-Host "PASS: $passed | FAIL: $failed | ERROR: $errors | NOT RUN: $notRun"
    Write-Host "`nIndividual ZIP archives: $(Join-Path $root 'eval/evidence')"
    Write-Host 'Lab remains active. After downloading evidence: ./scripts/environment/delete-environment-resource-group.ps1 -ResourceGroup rg-agentic-ops-lab'
}
if ($failedScenarios.Count -gt 0) { throw "Failed scripts: $($failedScenarios -join ', '). Review their individual evidence." }
