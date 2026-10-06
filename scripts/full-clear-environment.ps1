#Requires -Version 7.0
<#
.SYNOPSIS
Delete the complete PoC resource group, rather than only its Kubernetes workloads.
.DESCRIPTION
Deletes all resources in the named group. This does not clear the subscription,
other resource groups, local files or downloaded evidence.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroup
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI is required.'
}
$accountText = az account show --output json --only-show-errors
if ($LASTEXITCODE -ne 0) { throw 'Sign in to Azure CLI and select the intended subscription first.' }
$account = ($accountText -join "`n") | ConvertFrom-Json
$groupText = az group show --name $ResourceGroup --output json --only-show-errors
if ($LASTEXITCODE -ne 0) { throw "Resource group '$ResourceGroup' was not found or is not accessible." }
$group = ($groupText -join "`n") | ConvertFrom-Json
Write-Host "Subscription: $($account.name) ($($account.id))"
Write-Host "Full deletion target: $($group.id)"
Write-Host 'Save test evidence before deleting this lab.'
if ($PSCmdlet.ShouldProcess($group.id, 'Permanently delete the complete PoC resource group and its resources')) {
    $confirmation = Read-Host "Type '$ResourceGroup' to delete the entire group"
    if ($confirmation -cne $ResourceGroup) {
        throw 'Confirmation did not match. No resources were changed.'
    }
    # Wait for Azure to finish instead of reporting completion for a queued operation.
    az group delete --name $ResourceGroup --subscription $account.id --yes --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw 'Resource-group deletion failed. Inspect remaining resources in Azure.' }
    $exists = az group exists --name $ResourceGroup --subscription $account.id --output tsv --only-show-errors
    if ($LASTEXITCODE -ne 0 -or ($exists -join '').Trim() -ne 'false') {
        throw 'Could not confirm that the resource group was removed.'
    }
    Write-Host "Removed resource group: $ResourceGroup. Other groups and local evidence were not deleted."
}
