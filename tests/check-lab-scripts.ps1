#Requires -Version 7.0
$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
$temp=Join-Path ([IO.Path]::GetTempPath()) ('lab-check-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $temp 'scripts'),(Join-Path $temp '.local'),(Join-Path $temp 'bin') -Force | Out-Null
$pwsh=Join-Path $PSHOME 'pwsh'
$oldPath=$env:PATH
$passed=0
try {
    $kubeProgram=Join-Path $temp 'bin/kubectl'
    ("#!/bin/sh"+[Environment]::NewLine+"exit 0") | Set-Content $kubeProgram
    & chmod +x $kubeProgram
    $env:PATH=(Join-Path $temp 'bin')+[IO.Path]::PathSeparator+$oldPath
    @{subscriptionId='offline-subscription';resourceGroup='rg-agentic-ops-lab';demoImage='example.azurecr.io/payments-api:1.4.2';kubeconfig='recorded-config'} |
        ConvertTo-Json | Set-Content (Join-Path $temp '.local/rg-agentic-ops-lab.json')
    foreach ($id in '01','02','03','05','06') {
        $original=Get-Content (Join-Path $repo "scripts/test-s$id.ps1") -Raw
        $head=$original.Substring(0,$original.IndexOf('$goodImage ='))
        $check=@'
if ($config.subscriptionId -ne 'offline-subscription') { throw 'State not loaded.' }
if ($AcrLoginServer -ne 'example.azurecr.io') { throw 'Registry not loaded.' }
if ($Kubeconfig -ne 'explicit-config') { throw 'Explicit kubeconfig not retained.' }
'@
        $fixture=Join-Path $temp "scripts/test-s$id.ps1"
        ($head+$check) | Set-Content $fixture
        & $pwsh -NoProfile -File $fixture -AcrLoginServer example.azurecr.io -Kubeconfig explicit-config
        if ($LASTEXITCODE -ne 0) { throw "S$id initialization failed." }
        $passed++
        & $pwsh -NoProfile -File $fixture -AcrLoginServer other.azurecr.io -Kubeconfig explicit-config *> $null
        if ($LASTEXITCODE -eq 0) { throw "S$id accepted a mismatched registry." }
        $passed++
    }

    # Execute real preparation preflight against offline native-command substitutes.
    $azProgram=Join-Path $temp 'bin/az'
    $azFake=@'
#!/bin/sh
echo '{"fqdn":"recorded.example","privateFqdn":null}'
'@
    $kubeFake=@'
#!/bin/sh
echo 'https://different.example:443'
'@
    $azFake | Set-Content $azProgram
    $kubeFake | Set-Content $kubeProgram
    & chmod +x $azProgram $kubeProgram
    Copy-Item (Join-Path $repo 'scripts/prepare-test-environment.ps1') (Join-Path $temp 'scripts/prepare-test-environment.ps1')
    @{subscriptionId='offline-subscription';resourceGroup='rg-agentic-ops-lab';aksName='offline-aks';kubeconfig='recorded-config'} |
        ConvertTo-Json | Set-Content (Join-Path $temp '.local/rg-agentic-ops-lab.json')
    $preflight=@(& $pwsh -NoProfile -File (Join-Path $temp 'scripts/prepare-test-environment.ps1') -EvidenceDirectory (Join-Path $temp 'evidence') -Kubeconfig explicit-config 2>&1)
    if ($LASTEXITCODE -eq 0 -or ($preflight -join ' ') -notmatch 'kubeconfig differs from recorded lab') { throw 'Mismatched cluster preflight failed.' }
    $passed++

    $s03=Get-Content (Join-Path $repo 'scripts/test-s03.ps1') -Raw
    if (-not $s03.Contains("-split '\.'") -or ('example.azurecr.io' -split '\.')[0] -ne 'example') { throw 'S03 registry expression failed.' }
    $passed++
    $setup=Get-Content (Join-Path $repo 'scripts/setup-environment.ps1') -Raw
    $begin=$setup.IndexOf('$local ='); $end=$setup.IndexOf('$work =',$begin)
    $block=$setup.Substring($begin,$end-$begin)
    foreach ($exists in $false,$true) {
        $case=Join-Path $temp ("setup-"+$exists)
        New-Item -ItemType Directory -Force -Path (Join-Path $case '.local') | Out-Null
        $prior=@{
            subscriptionId='offline-subscription';resourceGroup='rg-agentic-ops-lab'
            location='polandcentral';aiLocation='swedencentral';nodeVmSize='Standard_D2as_v4'
            modelName='gpt-4.1-nano';modelVersion='2025-04-14'
            modelDeployment='diagnostic-gpt41nano';modelCapacity=10
            aiName='prior-account';acrName='prior-registry'
        }
        $prior | ConvertTo-Json | Set-Content (Join-Path $case '.local/rg-agentic-ops-lab.json')
        $root=$case; $ResourceGroup=$prior.resourceGroup; $SubscriptionId=$prior.subscriptionId
        $Location=$prior.location; $AiLocation=$prior.aiLocation; $NodeVmSize=$prior.nodeVmSize
        $ModelName=$prior.modelName; $ModelVersion=$prior.modelVersion
        $ModelDeployment=$prior.modelDeployment; $ModelCapacity=10
        $script:offlineGroupExists=$exists
        function Invoke-Az { param($Arguments) if ($script:offlineGroupExists) { 'true' } else { 'false' } }
        . ([scriptblock]::Create($block))
        if ($exists -and $state.aiName -ne 'prior-account') { throw 'Existing lab state replaced.' }
        if (-not $exists -and $state.aiName -eq 'prior-account') { throw 'Retired account name reused.' }
        if (-not $exists -and @(Get-ChildItem (Join-Path $case '.local/retired') -File).Count -ne 1) { throw 'Retired state missing.' }
        $passed++
    }
    foreach ($file in Get-ChildItem (Join-Path $repo 'scripts') -Filter '*.ps1') {
        $tokens=$null; $errors=$null
        [Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors) | Out-Null
        if ($errors.Count -gt 0) { throw "Parse errors in $($file.Name): $($errors.Message -join '; ')" }
    }
    Write-Host "$passed offline regression checks passed; PowerShell syntax valid."
} finally {
    $env:PATH=$oldPath
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
