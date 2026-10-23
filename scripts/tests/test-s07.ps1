#Requires -Version 7.0
<# Run one controlled S07 live trial. Does not provision Azure resources. #>
[CmdletBinding()]
param(
    [ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$ResourceGroup='rg-agentic-ops-lab',
    [string]$Kubeconfig,
    [ValidateRange(180,900)][int]$TimeoutSeconds=300,
    [switch]$PrepareBaseline,
    [string]$EvidenceRoot
)
& (Join-Path $PSScriptRoot '../internal/run-controlled-security-trial.ps1') -Scenario 'S07' @PSBoundParameters
