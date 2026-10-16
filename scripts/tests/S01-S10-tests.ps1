#Requires -Version 7.0
<#
.SYNOPSIS
Prepare the lab when absent, then run all ten live scenarios sequentially.
.DESCRIPTION
One entry point. Individual scenario implementations are reused so their evidence
and safety checks remain consistent. Shared Deployment mutations must not overlap.
The environment remains available after completion; deletion is a separate action.
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [ValidateRange(180,900)][int]$TimeoutSeconds=300,
    [switch]$StopOnFailure
)
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$false
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$scenarios=@('S01','S02','S03','S04','S05','S06','S07','S08','S09','S10')
foreach ($scenario in $scenarios) {
    $scriptPath=Join-Path $PSScriptRoot ("test-"+$scenario.ToLower()+".ps1")
    if (-not (Test-Path $scriptPath)) { throw "Missing scenario script: $scriptPath" }
}
$azProgram=(Get-Command az -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$statePath=Join-Path $root '.local/rg-agentic-ops-lab.json'
$state=$null
if (Test-Path $statePath) { $state=Get-Content $statePath -Raw | ConvertFrom-Json }
if ($state) {
    if ($SubscriptionId -and $SubscriptionId -ne $state.subscriptionId) { throw 'Subscription differs from recorded lab state.' }
    $SubscriptionId=$state.subscriptionId
} elseif (-not $SubscriptionId) {
    $SubscriptionId=(& $azProgram account show --query id -o tsv --only-show-errors | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $SubscriptionId) { throw 'Sign in to Azure first or pass -SubscriptionId.' }
}
$exists=(& $azProgram group exists --name rg-agentic-ops-lab --subscription $SubscriptionId -o tsv --only-show-errors | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot determine lab status.' }
if (-not $state -and $exists -eq 'true') { throw 'Lab group exists without setup state; automatic adoption refused.' }
if ($exists -eq 'false') {
    Write-Host 'Lab is absent. Running environment setup once before the ten scenarios.'
    & (Join-Path $PSScriptRoot '../environment/setup-environment.ps1') -SubscriptionId $SubscriptionId -ModelCapacity 10
    $state=Get-Content $statePath -Raw | ConvertFrom-Json
}
$batchId='S01-S10-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$batchDirectory=Join-Path $root (".local/evidence/batches/"+$batchId)
New-Item -ItemType Directory -Force -Path $batchDirectory | Out-Null
$rows=[Collections.Generic.List[object]]::new()
function Save-BatchSummary {
    @($script:rows.ToArray()) | ConvertTo-Json -Depth 20 | Set-Content (Join-Path $script:batchDirectory 'summary.json')
    $script:rows | Export-Csv (Join-Path $script:batchDirectory 'summary.csv') -NoTypeInformation -Encoding utf8
    $markdown=@(
        '# S01-S10 live functional batch',
        '',
        '| Scenario | Verdict | Outcome | Mode | Duration (s) |',
        '| --- | --- | --- | --- | ---: |'
    )
    foreach ($row in $script:rows) {
        $markdown+="| $($row.scenario) | $($row.verdict) | $($row.outcome) | $($row.mode) | $($row.durationSeconds) |"
    }
    $markdown+=@('','Scenarios run sequentially against one isolated lab. Each prepares a healthy baseline.',
        'S06, S08, S09 and S10 use scripted proposals; S07 uses the real model.',
        'Failed/inconclusive results remain recorded. This is one functional repetition per scenario.',
        'Archives are anonymized automatically before packaging.',
        'The lab is retained after the batch. Remove it with the existing cleanup script after downloading evidence.')
    $markdown | Set-Content (Join-Path $script:batchDirectory 'summary.md')
}
try {
    foreach ($scenario in $scenarios) {
        $scenarioDirectory=Join-Path $batchDirectory $scenario
        New-Item -ItemType Directory -Force -Path $scenarioDirectory | Out-Null
        $scenarioScript=Join-Path $PSScriptRoot ("test-"+$scenario.ToLower()+".ps1")
        $started=[DateTime]::UtcNow
        $clock=[Diagnostics.Stopwatch]::StartNew()
        $scenarioError=$null
        Write-Host "`n========== $scenario ($($scenarios.IndexOf($scenario)+1)/10) =========="
        try {
            $parameters=@{TimeoutSeconds=$TimeoutSeconds;EvidenceRoot=$scenarioDirectory}
            if ($scenario -in @('S07','S08','S09','S10')) { $parameters.PrepareBaseline=$true }
            & $scenarioScript @parameters
        } catch {
            $scenarioError=$_.Exception.Message
            Write-Warning "$scenario finished with an error; its result will remain in the batch summary."
        }
        $clock.Stop()
        # Each scenario has a separate empty evidence root; only this execution can
        # supply its result, so an old run is never mistaken for the current trial.
        $results=@(Get-ChildItem $scenarioDirectory -File -Recurse -Filter 'result.json')
        $result=$null
        if ($results.Count -eq 1) {
            try { $result=Get-Content $results[0].FullName -Raw | ConvertFrom-Json }
            catch { $scenarioError="Could not parse result.json: $_" }
        } elseif ($results.Count -gt 1) { $scenarioError='Multiple result files found; refusing to guess.' }
        $verdict='inconclusive'; $outcome='runner_error'
        if ($result -and $result.scenario -eq $scenario) {
            $verdict=$result.verdict; $outcome=$result.outcome
            if ($scenarioError -and $verdict -eq 'pass') { $verdict='inconclusive'; $outcome='runner_error_after_result' }
        }
        $mode=if ($scenario -in @('S06','S08','S09','S10')) { 'scripted proposal / live remediation' } elseif ($scenario -eq 'S07') { 'real model / controlled injection' } else { 'live agent workflow' }
        $archivePath=$null
        $archiveError=$null
        $archives=@(Get-ChildItem -LiteralPath $scenarioDirectory -File -Filter "$scenario-*-anonymized.zip")
        if ($archives.Count -eq 1) {
            try {
                $archiveRoot=Join-Path $root 'eval/evidence'
                New-Item -ItemType Directory -Force -Path $archiveRoot | Out-Null
                $archivePath=Join-Path $archiveRoot $archives[0].Name
                if (Test-Path -LiteralPath $archivePath) { throw 'Archive destination already exists.' }
                Copy-Item -LiteralPath $archives[0].FullName -Destination $archivePath -ErrorAction Stop
                Write-Host "$scenario ZIP: $archivePath"
            } catch { $archiveError=$_.Exception.Message; $archivePath=$null; Write-Warning "Archive export failed: $_" }
        } else { $archiveError='Expected exactly one anonymized scenario archive.' }
        $rows.Add([pscustomobject]@{
            scenario=$scenario;verdict=$verdict;outcome=$outcome;mode=$mode
            startedUtc=$started.ToString('o');durationSeconds=[Math]::Round($clock.Elapsed.TotalSeconds,1)
            evidenceDirectory=$scenarioDirectory;error=$scenarioError;zip=$archivePath;archiveError=$archiveError
        })
        Save-BatchSummary
        if ($StopOnFailure -and $verdict -ne 'pass') { break }
    }
} finally {
    if ($rows.Count -gt 0) { Save-BatchSummary }
    Write-Host "`n========== BATCH SUMMARY =========="
    $rows | Format-Table -Property @('scenario','verdict','outcome','durationSeconds') -AutoSize | Out-Host
    foreach ($row in $rows) { if ($row.zip) { Write-Host "$($row.scenario) ZIP: $($row.zip)" } }
    $bundle=Join-Path (Join-Path $root 'eval/evidence') ($batchId+'-anonymized.zip')
    $batchArchiveCreated=$false
    try {
        & (Join-Path $PSScriptRoot '../packaging/package-evidence.ps1') -SourceDirectory $batchDirectory -DestinationPath $bundle
        $bundle=(Resolve-Path -LiteralPath $bundle -ErrorAction Stop).Path
        $batchArchiveCreated=$true
        Write-Host "S01-S10 ZIP: $bundle"
    } catch { Write-Warning "Batch ZIP could not be created: $_" }
    Write-Host "Summary: $(Join-Path $batchDirectory 'summary.md')"
    Write-Host 'Lab remains active. After downloading evidence: ./scripts/environment/delete-environment-resource-group.ps1 -ResourceGroup rg-agentic-ops-lab'
}
if ($rows.Count -ne 10 -or @($rows | Where-Object { $_.verdict -ne 'pass' -or $_.archiveError }).Count -gt 0 -or -not $batchArchiveCreated) {
    throw "Batch contains failed, inconclusive, or unrun scenarios. Read summary.md in $batchDirectory."
}
