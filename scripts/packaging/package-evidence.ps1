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
# Probe interpreters: Windows Store aliases may exist without a Python install.
$pythonPath=$null
$pythonArguments=@()
foreach ($name in @('python','python3','py')) {
    $candidates=@(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue)
    foreach ($candidate in $candidates) {
        if ($IsWindows -and $candidate.Source -match '(?i)[\\/]Microsoft[\\/]WindowsApps[\\/]') { continue }
        $prefix=if ($name -eq 'py') { @('-3') } else { @() }
        try {
            $probe=& $candidate.Source @prefix -c 'import sys; print("EVIDENCE_PYTHON_OK" if sys.version_info >= (3, 11) else "UNSUPPORTED")' 2>$null
            if ($LASTEXITCODE -eq 0 -and $probe -eq 'EVIDENCE_PYTHON_OK') {
                $pythonPath=$candidate.Source
                $pythonArguments=$prefix
                break
            }
        } catch { continue }
    }
    if ($pythonPath) { break }
}
if (-not $pythonPath) { throw 'A working Python 3.11+ installation is required. Install Python, reopen Git Bash and retry packaging. Archive not created.' }
& $pythonPath @pythonArguments (Join-Path $PSScriptRoot 'sanitize-evidence.py') --source $SourceDirectory --destination $DestinationPath
if ($LASTEXITCODE -ne 0) { throw 'Evidence packaging failed. See the Python error above. Archive not created.' }
