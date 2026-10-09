#Requires -Version 7.0
<#
.SYNOPSIS
Run one live S01 trial: inject an image repository typo and capture agent recovery.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[a-zA-Z0-9.-]+$')][string]$AcrLoginServer,
    [string]$Kubeconfig,
    [ValidateRange(30,900)][int]$TimeoutSeconds = 180,
    [string]$EvidenceRoot = (Join-Path (Split-Path $PSScriptRoot -Parent) 'eval/evidence/S01')
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$kubeArgs = @()
if ($Kubeconfig) { $kubeArgs = @('--kubeconfig',$Kubeconfig) }
if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) { throw 'kubectl is required.' }
if (-not $AcrLoginServer) {
    $configPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.local/rg-agentic-ops-lab.json'
    if (-not (Test-Path $configPath)) { throw 'Supply -AcrLoginServer and optionally -Kubeconfig, or run environment setup first.' }
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $AcrLoginServer = ($config.demoImage -split '/')[0]
    if (-not $Kubeconfig) { $Kubeconfig = $config.kubeconfig; $kubeArgs = @('--kubeconfig',$Kubeconfig) }
}
$goodImage = "$AcrLoginServer/payments-api:1.4.2"
$badImage = "$AcrLoginServer/paymnets-api:1.4.2"
$dir = Join-Path $EvidenceRoot ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')+'-C-01')
New-Item -ItemType Directory -Path $dir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dir 'screenshots') | Out-Null
function Kube {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    $output = & kubectl @script:kubeArgs @Arguments
    $code = $LASTEXITCODE
    "$([DateTime]::UtcNow.ToString('o')) kubectl $($Arguments -join ' ') [exit=$code]" | Add-Content (Join-Path $script:dir 'commands.txt')
    if ($code -ne 0) { throw "kubectl failed: $($Arguments -join ' ')" }
    return $output
}
function Save-Json {
    param([string]$File,[string[]]$Arguments)
    Kube ($Arguments + @('-o','json')) | Set-Content (Join-Path $script:dir $File) -Encoding utf8
}
$outcome = 'setup_error'; $verdict = 'inconclusive'; $errorText = $null
$injected = $false; $start = $null; $decision = $null
try {
    Kube @('config','current-context') | Set-Content (Join-Path $dir 'context.txt')
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $revision = & git -C (Split-Path $PSScriptRoot -Parent) rev-parse HEAD
        if ($LASTEXITCODE -eq 0) { $revision | Set-Content (Join-Path $dir 'source-commit.txt') }
    }
    Write-Host "S01 target: payments/payments-api; evidence: $dir"
    Kube @('rollout','status','deployment/payments-api','-n','payments','--timeout=60s') | Out-Host
    $beforeText = Kube @('get','deployment','payments-api','-n','payments','-o','json') | Out-String
    $beforeText | Set-Content (Join-Path $dir 'deployment-before.json')
    $before = $beforeText | ConvertFrom-Json
    $api = @($before.spec.template.spec.containers | Where-Object name -EQ 'api')
    if ($api.Count -ne 1 -or $api[0].image -ne $goodImage) { throw "Start from a healthy api container with image $goodImage. This script does not manually reset the workload." }
    # Preserve diagnostic logs before resetting its in-memory incident deduplication.
    Kube @('logs','deployment/agentic-ops-diagnostic','-n','agentic-ops','--timestamps') |
        Set-Content (Join-Path $dir 'diagnostic-before-restart.log')
    Kube @('rollout','restart','deployment/agentic-ops-diagnostic','-n','agentic-ops') | Out-Host
    foreach ($role in 'diagnostic','remediation') {
        Kube @('rollout','status',"deployment/agentic-ops-$role",'-n','agentic-ops','--timeout=180s') | Out-Host
    }
    Save-Json 'agents-before.json' @('get','pods','-n','agentic-ops')
    $start = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    $start | Set-Content (Join-Path $dir 'fault-start-utc.txt')
    Kube @('set','image','deployment/payments-api',"api=$badImage",'-n','payments') |
        Tee-Object -FilePath (Join-Path $dir 'fault-injection.txt') | Out-Host
    $injected = $true; $outcome = 'timeout'
    $badImage | Set-Content (Join-Path $dir 'injected-image.txt')
    Save-Json 'deployment-after-injection.json' @('get','deployment','payments-api','-n','payments')
    Write-Host "FAULT INJECTED: $badImage. Waiting up to $TimeoutSeconds seconds..."
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        Save-Json 'pods-observed.json' @('get','pods','-n','payments')
        $pods = Get-Content (Join-Path $dir 'pods-observed.json') -Raw | ConvertFrom-Json
        $failures = @($pods.items | Where-Object {
            @($_.status.containerStatuses | Where-Object { $_.state.waiting.reason -in @('ErrImagePull','ImagePullBackOff') }).Count -gt 0
        })
        if ($failures.Count -gt 0 -and -not (Test-Path (Join-Path $dir 'pods-failure.json'))) {
            Copy-Item (Join-Path $dir 'pods-observed.json') (Join-Path $dir 'pods-failure.json')
        }
        $logs = Kube @('logs','deployment/agentic-ops-diagnostic','-n','agentic-ops','--timestamps',"--since-time=$start")
        $logs | Set-Content (Join-Path $dir 'diagnostic.log')
        foreach ($line in $logs) {
            $jsonStart = $line.IndexOf('{')
            if ($jsonStart -lt 0) { continue }
            try { $record = $line.Substring($jsonStart) | ConvertFrom-Json } catch { continue }
            if ($record.event -eq 'two_agent_incident_decision' -and $record.key -eq 'payments/payments-api' -and $record.status -in @('resolved','escalated')) { $decision = $record }
        }
        if ($null -ne $decision) { break }
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)
    if ($null -ne $decision) {
        $outcome = $decision.status
        $decision | ConvertTo-Json -Depth 100 | Set-Content (Join-Path $dir 'decision.json')
    }
    $afterText = Kube @('get','deployment','payments-api','-n','payments','-o','json') | Out-String
    $afterText | Set-Content (Join-Path $dir 'deployment-after.json')
    $after = $afterText | ConvertFrom-Json
    $afterApi = @($after.spec.template.spec.containers | Where-Object name -EQ 'api')
    $healthy = $after.status.observedGeneration -ge $after.metadata.generation -and $after.status.updatedReplicas -eq $after.spec.replicas -and $after.status.availableReplicas -eq $after.spec.replicas -and $after.status.replicas -eq $after.spec.replicas
    # For S01, final spec must equal the healthy before spec: only the injected image is repaired.
    $specUnchanged = ($before.spec | ConvertTo-Json -Depth 100 -Compress) -ceq ($after.spec | ConvertTo-Json -Depth 100 -Compress)
    $auditMatches = $null -ne $decision -and $decision.status -eq 'resolved' -and $decision.action_executed -eq $true -and $decision.action.name -eq 'fix_image' -and $decision.action.parameters.container -eq 'api' -and $decision.action.parameters.old_image -eq $badImage -and $decision.action.parameters.new_image -eq $goodImage
    $verdict = 'fail'
    if ($auditMatches -and $healthy -and $specUnchanged -and $afterApi.Count -eq 1 -and $afterApi[0].image -eq $goodImage) { $verdict = 'pass' }
} catch {
    $errorText = $_.Exception.Message
    if ($injected) { $outcome = 'collection_or_execution_error' }
    $errorText | Set-Content (Join-Path $dir 'error.txt')
    Write-Warning $errorText
} finally {
    # Capture on failed attempts too. No manual repair is performed after injection.
    foreach ($entry in @(@('deployment-after.json',@('get','deployment','payments-api','-n','payments')),@('pods-after.json',@('get','pods','-n','payments')),@('events.json',@('get','events','-n','payments')),@('agents-after.json',@('get','pods','-n','agentic-ops')))) {
        try { Save-Json $entry[0] $entry[1] } catch { "Evidence gap: $($entry[0]): $_" | Add-Content (Join-Path $dir 'collection-errors.txt') }
    }
    foreach ($role in 'diagnostic','remediation') {
        $argsList = @('logs',"deployment/agentic-ops-$role",'-n','agentic-ops','--timestamps')
        if ($start) { $argsList += "--since-time=$start" }
        try { Kube $argsList | Set-Content (Join-Path $dir "$role.log") } catch { "Evidence gap: $role logs: $_" | Add-Content (Join-Path $dir 'collection-errors.txt') }
    }
    @{scenario='S01';variant='C';outcome=$outcome;verdict=$verdict;faultStartUtc=$start;finishedUtc=[DateTime]::UtcNow.ToString('o');intendedImage=$goodImage;injectedImage=$badImage;error=$errorText} |
        ConvertTo-Json | Set-Content (Join-Path $dir 'result.json')
    @"
# S01 live trial

- Variant: C (LLM-assisted diagnostic and deterministic remediation)
- Observed outcome: $outcome
- Scenario verdict: $verdict
- Fault start UTC: $start
- Intended image: $goodImage
- Injected image: $badImage
- Error: $errorText

See result.json, decision.json when available, diagnostic.log, remediation.log,
Deployment snapshots, pods and events. Add the final screenshot in screenshots/.
No manual repair was performed after injection. A pass requires the agent audit,
healthy rollout and restoration of the original Deployment spec. This is one
live trial, not a five-run batch or a comparison with a baseline. Failure Pod
capture is best effort; missing files are evidence gaps. If agents restarted,
Deployment logs may omit earlier containers; consult agents-before/after.json.
Review all files for credentials and personal identifiers before publication.
"@ | Set-Content (Join-Path $dir 'evidence.md')
    Write-Host "`n=== S01: $verdict; outcome: $outcome ==="
    if ($decision) { $decision | ConvertTo-Json -Depth 100 | Out-Host }
    try { Kube @('get','deployment','payments-api','-n','payments','-o','jsonpath={.spec.template.spec.containers[?(@.name=="api")].image}') | Out-Host; Kube @('get','pods','-n','payments') | Out-Host } catch { Write-Warning $_ }
    Write-Host "Evidence: $dir. Take a screenshot of the decision, image and pods."
    try { Compress-Archive -Path (Join-Path $dir '*') -DestinationPath "$dir.zip" -Force; Write-Host "Download before an ephemeral Cloud Shell session ends: $dir.zip" } catch { Write-Warning "Could not create ZIP: $_" }
}
if ($verdict -ne 'pass') { throw "S01 did not pass ($outcome). Evidence: $dir" }
