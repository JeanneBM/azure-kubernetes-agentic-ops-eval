#Requires -Version 7.0
<# Controlled live handoff trials. Uses an existing lab; never provisions Azure. #>
[CmdletBinding()]
param(
    [ValidateSet('rg-agentic-ops-lab')][string]$ResourceGroup='rg-agentic-ops-lab'
)
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$false
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$pythonPath=$null
$prefix=@()
foreach ($name in @('python','python3','py')) {
    foreach ($candidate in @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue)) {
        if ($IsWindows -and $candidate.Source -match '(?i)[\\/]Microsoft[\\/]WindowsApps[\\/]') { continue }
        $arguments=if ($name -eq 'py') { @('-3') } else { @() }
        try {
            $probe=& $candidate.Source @arguments -c 'import sys; print("OK" if sys.version_info >= (3, 11) else "OLD")' 2>$null
            if ($LASTEXITCODE -eq 0 -and $probe -eq 'OK') { $pythonPath=$candidate.Source; $prefix=$arguments; break }
        } catch { continue }
    }
    if ($pythonPath) { break }
}
if (-not $pythonPath) { throw 'Python 3.11+ is required.' }
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
Write-Host 'Handoff trials: pauses automatic diagnostics, injects two image typos, restores baseline and original replica count.'
Write-Host 'No Azure provisioning; no model calls. Allow approximately 5-10 minutes.'
$runName=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'-'+[Guid]::NewGuid().ToString('N').Substring(0,6)
$source=Join-Path $root ('.local/evidence/handoff/'+$runName)
& $pythonPath @prefix (Join-Path $root 'eval/handoff/run.py') --resource-group $ResourceGroup --evidence-dir $source
$trialExit=$LASTEXITCODE
if (Test-Path (Join-Path $source 'summary.json')) {
    $destination=Join-Path $root ("eval/evidence/handoff-"+$runName+'-anonymized.zip')
    & (Join-Path $root 'scripts/packaging/package-evidence.ps1') -SourceDirectory $source -DestinationPath $destination
    Write-Host "Archive: $destination"
}
if ($trialExit -ne 0) { throw 'Handoff trials did not both pass. Read summary.json and cleanup_errors before proceeding.' }
