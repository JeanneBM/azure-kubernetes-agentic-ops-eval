#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceDirectory,
    [Parameter(Mandatory)][string]$DestinationPath
)
$ErrorActionPreference='Stop'
if ($DestinationPath -notmatch '(?i)-anonymized\.zip$') { throw 'Destination must end with -anonymized.zip.' }
$PSNativeCommandUseErrorActionPreference=$false
# Never retain an outdated output when packaging cannot complete.
if (Test-Path $DestinationPath) { Remove-Item -LiteralPath $DestinationPath -Force }
$python=Get-Command python3 -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $python) { $python=Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1 }
if (-not $python) { throw 'Python 3 is required. Archive not created.' }
& $python.Source (Join-Path $PSScriptRoot 'sanitize-evidence.py') --source $SourceDirectory --destination $DestinationPath
if ($LASTEXITCODE -ne 0) { throw 'Evidence packaging failed. Archive not created.' }
