# Shared lab lifecycle helpers. No Azure calls or mutations on import.
function Invoke-LabKubectl {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$Kubeconfig,
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$CommandLog,
        [ValidateRange(1,10)][int]$LogAttempts=4,
        [ValidateRange(0,5)][int]$RetryDelaySeconds=2
    )
    # Only read-only log requests retry; never replay patches or evaluator writes.
    $limit=if ($Arguments[0] -eq 'logs') { $LogAttempts } else { 1 }
    for ($attempt=1; $attempt -le $limit; $attempt++) {
        $output=& $Executable --kubeconfig $Kubeconfig @Arguments
        $exitCode=$LASTEXITCODE
        if ($CommandLog) {
            "$([DateTime]::UtcNow.ToString('o')) kubectl $($Arguments -join ' ') [exit=$exitCode attempt=$attempt]" | Add-Content $CommandLog
        }
        if ($exitCode -eq 0) { return $output }
        if ($attempt -lt $limit) { Start-Sleep -Seconds $RetryDelaySeconds }
    }
    throw "kubectl failed after $limit attempt(s): $($Arguments -join ' ')"
}

function Test-LabAgentReady {
    param($Deployment, $Pods)
    if ($Deployment.spec.replicas -ne 1) { return $false }
    $s=$Deployment.status
    if (-not $s -or $s.observedGeneration -lt $Deployment.metadata.generation -or
        $s.replicas -ne 1 -or $s.updatedReplicas -ne 1 -or
        $s.readyReplicas -ne 1 -or $s.availableReplicas -ne 1) { return $false }
    $active=@($Pods.items | Where-Object { -not $_.metadata.deletionTimestamp })
    if ($active.Count -ne 1 -or $active[0].status.phase -ne 'Running') { return $false }
    $containers=@($active[0].status.containerStatuses)
    if ($containers.Count -ne 1 -or -not $containers[0].ready) { return $false }
    return $containers[0].image -eq $Deployment.spec.template.spec.containers[0].image
}

function Wait-LabAgentReady {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$Kubeconfig,
        [ValidateSet('diagnostic','remediation')][string]$Role,
        [ValidateRange(1,300)][int]$TimeoutSeconds=120,
        [string]$CommandLog
    )
    $clock=[Diagnostics.Stopwatch]::StartNew()
    do {
        $dep=Invoke-LabKubectl -Executable $Executable -Kubeconfig $Kubeconfig -CommandLog $CommandLog -Arguments @('get',"deployment/agentic-ops-$Role",'-n','agentic-ops','-o','json') | Out-String | ConvertFrom-Json
        $pods=Invoke-LabKubectl -Executable $Executable -Kubeconfig $Kubeconfig -CommandLog $CommandLog -Arguments @('get','pods','-n','agentic-ops','-l',"app=agentic-ops,role=$Role",'-o','json') | Out-String | ConvertFrom-Json
        if (Test-LabAgentReady $dep $pods) { return }
        if ($clock.Elapsed.TotalSeconds -ge $TimeoutSeconds) { break }
        Start-Sleep -Milliseconds 500
    } while ($true)
    throw "Agent $Role did not converge to one ready current-generation replica within $TimeoutSeconds seconds."
}
