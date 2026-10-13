#Requires -Version 7.0
<#
.SYNOPSIS
Prepare the isolated lab for the next functional trial; prior evidence is preserved.
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup='rg-agentic-ops-lab',
    [string]$Kubeconfig,
    [Parameter(Mandatory)][string]$EvidenceDirectory,
    [ValidateRange(1,100)][int]$MinimumModelCapacity=10
)
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$false
$root=Split-Path $PSScriptRoot -Parent
$statePath=Join-Path $root ".local/$ResourceGroup.json"
$lab=Get-Content $statePath -Raw | ConvertFrom-Json
if ($Kubeconfig) { $lab.kubeconfig = $Kubeconfig }
if (-not $lab.kubeconfig) { throw 'Explicit lab kubeconfig is required.' }
$azProgram=(Get-Command az -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$kubectlProgram=(Get-Command kubectl -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
function Invoke-PrepareAz {
    param([string[]]$Arguments)
    $output=& $script:azProgram @Arguments --subscription $script:lab.subscriptionId --only-show-errors -o json
    if ($LASTEXITCODE -ne 0) { throw 'Lab preparation Azure operation failed; no test fault injected.' }
    if ($output) { $output | Out-String | ConvertFrom-Json }
}
function Invoke-PrepareKube {
    param([string[]]$Arguments)
    $output=& $script:kubectlProgram --kubeconfig $script:lab.kubeconfig @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Lab preparation kubectl failed: $($Arguments -join ' ')" }
    $output
}
$prep=Join-Path $EvidenceDirectory 'preparation'
New-Item -ItemType Directory -Force -Path $prep | Out-Null
Write-Host 'PREPARE: model capacity, healthy baseline, and agent readiness.'
$aks=Invoke-PrepareAz @('aks','show','-g',$ResourceGroup,'-n',$lab.aksName)
$server=(Invoke-PrepareKube @('config','view','--minify','-o','jsonpath={.clusters[0].cluster.server}') | Out-String).Trim()
if (([uri]$server).Host -notin @($aks.fqdn,$aks.privateFqdn)) { throw 'Refusing preparation: kubeconfig differs from recorded lab.' }
$model=Invoke-PrepareAz @('cognitiveservices','account','deployment','show','-g',$ResourceGroup,'-n',$lab.aiName,'--deployment-name',$lab.modelDeployment)
if ($model.properties.model.name -ne $lab.modelName -or $model.properties.model.version -ne $lab.modelVersion -or $model.sku.name -ne 'GlobalStandard') { throw 'Model configuration differs from lab state.' }
$model | ConvertTo-Json -Depth 30 | Set-Content (Join-Path $prep 'model-before.json')
$capacity=[Math]::Max($MinimumModelCapacity,[int]$model.sku.capacity)
if ([int]$model.sku.capacity -lt $capacity) {
    $model=Invoke-PrepareAz @('cognitiveservices','account','deployment','create','-g',$ResourceGroup,'-n',$lab.aiName,'--deployment-name',$lab.modelDeployment,'--model-name',$lab.modelName,'--model-version',$lab.modelVersion,'--model-format','OpenAI','--sku-name','GlobalStandard','--sku-capacity',"$capacity")
}
if ($model.properties.provisioningState -ne 'Succeeded') { throw 'Model deployment is not ready.' }
$lab.modelCapacity=[int]$model.sku.capacity
$lab | ConvertTo-Json -Depth 30 | Set-Content $statePath
$model | ConvertTo-Json -Depth 30 | Set-Content (Join-Path $prep 'model-ready.json')
# Restore only the known kubelet lab role if an interrupted S04 removed it.
$acr=Invoke-PrepareAz @('acr','show','-g',$ResourceGroup,'-n',$lab.acrName)
if (($lab.demoImage -split '/')[0] -ne $acr.loginServer) { throw 'Lab image registry mismatch.' }
$principal=$aks.identityProfile.kubeletidentity.objectId
$roles=@(Invoke-PrepareAz @('role','assignment','list','--assignee',$principal,'--scope',$acr.id,'--include-inherited'))
if (@($roles | Where-Object { $_.roleDefinitionName -eq 'AcrPull' -and $_.scope -eq $acr.id }).Count -eq 0) {
    Invoke-PrepareAz @('role','assignment','create','--assignee-object-id',$principal,'--assignee-principal-type','ServicePrincipal','--role','AcrPull','--scope',$acr.id) | Out-Null
}
$deployment=Invoke-PrepareKube @('get','deployment/payments-api','-n','payments','-o','json') | Out-String | ConvertFrom-Json
$deployment | ConvertTo-Json -Depth 100 | Set-Content (Join-Path $prep 'deployment-before-reset.json')
$containers=@($deployment.spec.template.spec.containers)
if (@($containers | Where-Object { $_.name -notin @('api','metrics') }).Count -gt 0 -or @($containers | Where-Object name -EQ 'api').Count -ne 1) { throw 'Unexpected workload containers; automatic reset refused.' }
$diagnostic=Invoke-PrepareKube @('get','deployment/agentic-ops-diagnostic','-n','agentic-ops','-o','json') | Out-String | ConvertFrom-Json
if ($diagnostic.spec.replicas -gt 1) { throw 'Expected isolated single-replica diagnostic agent.' }
# Build only when application inputs changed; documentation edits do not rebuild agents.
$inputs=@(Get-ChildItem (Join-Path $root 'src') -Recurse -File -Filter '*.py')
$inputs+=@(Get-Item (Join-Path $root 'Dockerfile'),(Join-Path $root 'pyproject.toml'),(Join-Path $root 'constraints.txt'))
$fingerprint=($inputs | Sort-Object FullName | ForEach-Object {
    $_.FullName.Substring($root.Length) + ':' + (Get-FileHash $_.FullName -Algorithm SHA256).Hash
}) -join '|'
$hashBytes=[Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($fingerprint))
$imageTag='trial-'+([Convert]::ToHexString($hashBytes).ToLower().Substring(0,16))
$desiredAgentImage="$($acr.loginServer)/agentic-ops:$imageTag"
$rebuild=$lab.agentImage -ne $desiredAgentImage
if ($rebuild) {
    Write-Host "PREPARE: application changed; building agent image $imageTag once."
    $buildArgs=@('acr','build','--registry',$lab.acrName,'--image',"agentic-ops:$imageTag",$root,'--subscription',$lab.subscriptionId,'--only-show-errors')
    & $azProgram @buildArgs | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Agent image build failed; no test fault injected.' }
}
$paused=$false
try {
    # Reset before observation resumes; this also clears incident deduplication.
    $paused=$true
    Invoke-PrepareKube @('scale','deployment/agentic-ops-diagnostic','-n','agentic-ops','--replicas=0') | Out-Host
    Invoke-PrepareKube @('wait','--for=delete','pods','-n','agentic-ops','-l','app=agentic-ops,role=diagnostic','--timeout=60s') | Out-Host
    if ($rebuild) {
        foreach ($agentRole in 'diagnostic','remediation') {
            $agentDeployment=Invoke-PrepareKube @('get',"deployment/agentic-ops-$agentRole",'-n','agentic-ops','-o','json') | Out-String | ConvertFrom-Json
            $agentContainers=@($agentDeployment.spec.template.spec.containers)
            if ($agentContainers.Count -ne 1) { throw 'Expected a single container in each agent Deployment.' }
            Invoke-PrepareKube @('set','image',"deployment/agentic-ops-$agentRole","$($agentContainers[0].name)=$desiredAgentImage",'-n','agentic-ops') | Out-Host
        }
    }
    $resetContainers=@(@{name='api';image=$lab.demoImage;imagePullPolicy='Always'})
    if (@($containers | Where-Object name -EQ 'metrics').Count -gt 0) { $resetContainers+=@{name='metrics';'$patch'='delete'} }
    $patch=@{spec=@{template=@{metadata=@{annotations=@{'eval.preparation/run'=[Guid]::NewGuid().ToString('N')}};spec=@{containers=$resetContainers}}}} | ConvertTo-Json -Depth 20
    $patchPath=Join-Path $prep 'reset-patch.json'
    $patch | Set-Content $patchPath
    Invoke-PrepareKube @('patch','deployment/payments-api','-n','payments','--type=strategic','--patch-file',$patchPath) | Out-Host
    Invoke-PrepareKube @('rollout','status','deployment/payments-api','-n','payments','--timeout=180s') | Out-Host
} finally {
    if ($paused) { Invoke-PrepareKube @('scale','deployment/agentic-ops-diagnostic','-n','agentic-ops','--replicas=1') | Out-Host }
}
foreach ($role in 'diagnostic','remediation') {
    Invoke-PrepareKube @('rollout','status',"deployment/agentic-ops-$role",'-n','agentic-ops','--timeout=120s') | Out-Host
}
Invoke-PrepareKube @('get','deployment/payments-api','-n','payments','-o','json') | Set-Content (Join-Path $prep 'deployment-healthy.json')
if ($rebuild) {
    $lab.agentImage=$desiredAgentImage
    $lab.imageTag=$imageTag
    $lab | ConvertTo-Json -Depth 30 | Set-Content $statePath
}
Write-Host 'PREPARE COMPLETE: healthy single-container baseline; test can inject its fault.'
