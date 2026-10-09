#Requires -Version 7.0
<#
.SYNOPSIS
Run one live S02 trial: prepare a healthy sidecar, inject an API image typo and capture recovery.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[a-zA-Z0-9.-]+$')][string]$AcrLoginServer,
    [string]$Kubeconfig,
    [ValidateRange(30,900)][int]$TimeoutSeconds = 180,
    [string]$EvidenceRoot = (Join-Path (Split-Path $PSScriptRoot -Parent) 'eval/evidence/S02')
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
    Write-Host "S02 target: payments/payments-api; evidence: $dir"
    Kube @('rollout','status','deployment/payments-api','-n','payments','--timeout=60s') | Out-Host
    # Record preparation separately from the fault/recovery comparison.
    Save-Json 'deployment-before-preparation.json' @('get','deployment','payments-api','-n','payments')
    $initial = Get-Content (Join-Path $dir 'deployment-before-preparation.json') -Raw | ConvertFrom-Json
    $initialApi = @($initial.spec.template.spec.containers | Where-Object name -EQ 'api')
    if ($initialApi.Count -ne 1 -or $initialApi[0].image -ne $goodImage) { throw "Start with a healthy api using $goodImage." }
    $sidecars = @($initial.spec.template.spec.containers | Where-Object name -NE 'api')
    if ($sidecars.Count -eq 0) {
        $patchPath = Join-Path $dir 'sidecar-preparation.json'
        @{spec=@{template=@{spec=@{containers=@(@{name='metrics';image=$goodImage;command=@('/bin/sh','-c','while true; do sleep 3600; done')})}}}} |
            ConvertTo-Json -Depth 10 | Set-Content $patchPath -Encoding utf8
        Kube @('patch','deployment','payments-api','-n','payments','--type=strategic','--patch-file',$patchPath) | Out-Host
    } elseif ($sidecars.Count -ne 1 -or $sidecars[0].name -ne 'metrics') {
        throw 'S02 requires api plus exactly one metrics sidecar; unrelated containers will not be replaced.'
    }
    Kube @('rollout','status','deployment/payments-api','-n','payments','--timeout=180s') | Out-Host
    $beforeText = Kube @('get','deployment','payments-api','-n','payments','-o','json') | Out-String
    $beforeText | Set-Content (Join-Path $dir 'deployment-before.json')
    $before = $beforeText | ConvertFrom-Json
    Save-Json 'replicasets-before.json' @('get','replicasets','-n','payments','-l','app=payments-api')
    $replicaSets = Get-Content (Join-Path $dir 'replicasets-before.json') -Raw | ConvertFrom-Json
    $deploymentRevision = $before.metadata.annotations.'deployment.kubernetes.io/revision'
    $currentReplicaSets = @($replicaSets.items | Where-Object {
        $_.metadata.annotations.'deployment.kubernetes.io/revision' -eq $deploymentRevision -and
        @($_.metadata.ownerReferences | Where-Object { $_.kind -eq 'Deployment' -and $_.uid -eq $before.metadata.uid }).Count -eq 1
    })
    if ($currentReplicaSets.Count -ne 1) { throw 'Cannot identify the current payments-api ReplicaSet before injection.' }
    Save-Json 'pods-before.json' @('get','pods','-n','payments','-l','app=payments-api')
    $baselinePods = Get-Content (Join-Path $dir 'pods-before.json') -Raw | ConvertFrom-Json
    # Old or terminating Pods may remain visible after rollout status succeeds.
    $activePods = @($baselinePods.items | Where-Object {
        -not $_.metadata.deletionTimestamp -and
        @($_.metadata.ownerReferences | Where-Object { $_.kind -eq 'ReplicaSet' -and $_.uid -eq $currentReplicaSets[0].metadata.uid }).Count -eq 1
    })
    ConvertTo-Json -InputObject @($activePods) -Depth 100 | Set-Content (Join-Path $dir 'pods-baseline-active.json')
    if ($before.spec.replicas -lt 1 -or $activePods.Count -ne $before.spec.replicas) {
        throw "Expected $($before.spec.replicas) active current-revision Pods before injection; found $($activePods.Count)."
    }
    foreach ($pod in $activePods) {
        $metrics = @($pod.status.containerStatuses | Where-Object name -EQ 'metrics')
        if ($metrics.Count -ne 1 -or -not $metrics[0].ready -or -not $metrics[0].state.running) {
            throw "The metrics sidecar must be running and ready before injection (Pod: $($pod.metadata.name))."
        }
    }
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
    # For S02, final spec must equal the healthy before spec: only the injected image is repaired.
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
    @{scenario='S02';variant='C';outcome=$outcome;verdict=$verdict;faultStartUtc=$start;finishedUtc=[DateTime]::UtcNow.ToString('o');intendedImage=$goodImage;injectedImage=$badImage;error=$errorText} |
        ConvertTo-Json | Set-Content (Join-Path $dir 'result.json')
    @"
# S02 live trial

- Variant: C (LLM-assisted diagnostic and deterministic remediation)
- Observed outcome: $outcome
- Scenario verdict: $verdict
- Fault start UTC: $start
- Intended image: $goodImage
- Injected image: $badImage
- Error: $errorText

See result.json, decision.json when available, diagnostic.log, remediation.log,
Deployment snapshots, pods and events. deployment-before.json includes the healthy metrics sidecar; deployment-before-preparation.json records the original workload. Add the final screenshot in screenshots/.
No manual repair was performed after injection. A pass requires the agent audit,
healthy rollout and restoration of the pre-injection Deployment spec, including the unchanged sidecar. Sidecar preparation occurs before injection and is retained after the trial. This is one
live trial, not a five-run batch or a comparison with a baseline. Failure Pod
capture is best effort; missing files are evidence gaps. If agents restarted,
Deployment logs may omit earlier containers; consult agents-before/after.json.
Review all files for credentials and personal identifiers before publication.
"@ | Set-Content (Join-Path $dir 'evidence.md')
    Write-Host "`n=== S02: $verdict; outcome: $outcome ==="
    if ($decision) { $decision | ConvertTo-Json -Depth 100 | Out-Host }
    try { Kube @('get','deployment','payments-api','-n','payments','-o','jsonpath={.spec.template.spec.containers[0].image}') | Out-Host; Kube @('get','pods','-n','payments') | Out-Host } catch { Write-Warning $_ }
    Write-Host "Evidence: $dir. Take a screenshot of the decision, image and pods."
    try { Compress-Archive -Path (Join-Path $dir '*') -DestinationPath "$dir.zip" -Force; Write-Host "Download before an ephemeral Cloud Shell session ends: $dir.zip" } catch { Write-Warning "Could not create ZIP: $_" }
}
if ($verdict -ne 'pass') { throw "S02 did not pass ($outcome). Evidence: $dir" }
