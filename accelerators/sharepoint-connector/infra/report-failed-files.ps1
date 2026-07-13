<#
.SYNOPSIS
    Reports files the connector attempted to index but that FAILED, by reading the
    Azure Table Storage 'failedFiles' table. No Microsoft Graph / Sites.Read.All needed.

.DESCRIPTION
    The connector records every per-file failure in a Storage table (default: failedFiles)
    via StateStore.record_failed_file(). Each row is keyed by the SharePoint drive item_id
    and carries the real failure reason (last_error), the retry counter (failure_count),
    whether it was terminally poisoned (terminal), and when it was last seen.

    This is the authoritative "why didn't this file index" source — unlike the best-effort
    guesses in find-unindexed-approved-files.ps1 — and it only requires a storage.azure.com
    AAD token (Storage Table Data Reader), NOT a SharePoint Graph scope.

    READ-ONLY. Never writes to storage, the index, or SharePoint.

.EXAMPLE
    ./report-failed-files.ps1
#>

[CmdletBinding()]
param(
    [string]$StorageAccount = "<your-storage-account>",
    [string]$Table          = "failedFiles",
    [string]$SubscriptionId = "<your-subscription-id>",
    [string]$OutputCsv      = ".\unindexed-files-report.csv"
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

$azWin = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin"
if (Test-Path $azWin) { $env:PATH = "$azWin;" + $env:PATH }

if ($SubscriptionId) { az account set --subscription $SubscriptionId 2>&1 | Out-Null }

Write-Host "==> Acquiring storage.azure.com token..." -ForegroundColor Cyan
$token = az account get-access-token --resource "https://storage.azure.com" --query accessToken -o tsv
if (-not $token) { throw "Failed to acquire a storage token." }

$headers = @{
    Authorization        = "Bearer $token"
    "x-ms-version"       = "2019-12-12"
    "x-ms-date"          = (Get-Date).ToUniversalTime().ToString("R")
    Accept               = "application/json;odata=nometadata"
    DataServiceVersion   = "3.0"
}

Write-Host "==> Reading '$Table' table from '$StorageAccount'..." -ForegroundColor Cyan
$rows = New-Object System.Collections.Generic.List[object]
$uri  = "https://$StorageAccount.table.core.windows.net/$Table()"
do {
    $resp = Invoke-WebRequest -Uri $uri -Headers $headers -Method Get -UseBasicParsing
    $data = $resp.Content | ConvertFrom-Json
    foreach ($e in $data.value) { $rows.Add($e) }

    $nextPk = $resp.Headers["x-ms-continuation-NextPartitionKey"]
    $nextRk = $resp.Headers["x-ms-continuation-NextRowKey"]
    if ($nextPk) {
        $uri = "https://$StorageAccount.table.core.windows.net/$Table()?NextPartitionKey=$([Uri]::EscapeDataString([string]$nextPk))&NextRowKey=$([Uri]::EscapeDataString([string]$nextRk))"
    } else {
        $uri = $null
    }
} while ($uri)

$out = $rows | ForEach-Object {
    [pscustomobject]@{
        ItemId       = $_.RowKey
        FailureCount = [int]($_.failure_count)
        Terminal     = [bool]($_.terminal)
        LastSeen     = $_.last_seen_iso
        LastError    = ([string]$_.last_error) -replace "\s+", " "
    }
} | Sort-Object -Property @{Expression = "Terminal"; Descending = $true}, @{Expression = "FailureCount"; Descending = $true}

$out | Export-Csv -Path $OutputCsv -NoTypeInformation -Encoding UTF8
$full = (Resolve-Path $OutputCsv).Path

Write-Host ""
Write-Host "==================== RESULT ====================" -ForegroundColor Green
Write-Host ("Failed files recorded : {0}" -f $out.Count)
Write-Host ("Terminal (poisoned)   : {0}" -f (@($out | Where-Object { $_.Terminal }).Count)) -ForegroundColor Yellow
Write-Host ("CSV written to        : {0}" -f $full)
Write-Host "-----------------------------------------------"
Write-Host "Top error patterns:"
$out | Group-Object { ($_.LastError.Substring(0, [Math]::Min(80, $_.LastError.Length))) } |
    Sort-Object Count -Descending | Select-Object -First 10 | ForEach-Object {
        Write-Host ("  {0,4} x {1}" -f $_.Count, $_.Name)
    }
Write-Host "==============================================="
