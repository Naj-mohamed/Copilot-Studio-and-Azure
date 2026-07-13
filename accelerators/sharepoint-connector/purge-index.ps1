param(
    [string]$Subscription = "<your-subscription-id>",
    [string]$Rg = "<your-resource-group>",
    [string]$SearchSvc = "<your-search-service>",
    [string]$Index = "sharepoint-index",
    [string]$ApiVersion = "2024-07-01"
)

$ErrorActionPreference = "Stop"
az account set --subscription $Subscription | Out-Null

$key = az search admin-key show --service-name $SearchSvc --resource-group $Rg --query primaryKey -o tsv
$base = "https://$SearchSvc.search.windows.net/indexes/$Index/docs"
$headers = @{ "api-key" = $key; "Content-Type" = "application/json" }

$searchUri = "$base/search?api-version=$ApiVersion"
$indexUri  = "$base/index?api-version=$ApiVersion"

$totalDeleted = 0
while ($true) {
    $body = @{ search = "*"; select = "chunk_id"; top = 1000 } | ConvertTo-Json
    $res = Invoke-RestMethod -Uri $searchUri -Method Post -Headers $headers -Body $body
    $docs = $res.value
    if (-not $docs -or $docs.Count -eq 0) { break }

    $actions = @()
    foreach ($d in $docs) {
        $actions += @{ "@search.action" = "delete"; "chunk_id" = $d.chunk_id }
    }
    $delBody = @{ value = $actions } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Uri $indexUri -Method Post -Headers $headers -Body $delBody | Out-Null
    $totalDeleted += $docs.Count
    Write-Host ("Deleted batch of {0} (total {1})" -f $docs.Count, $totalDeleted)
}

# Confirm empty
$cntUri = "$base/`$count?api-version=$ApiVersion"
Start-Sleep -Seconds 3
$remaining = Invoke-RestMethod -Uri $cntUri -Method Get -Headers $headers
Write-Host ("Purge complete. Total deleted: {0}. Remaining docs: {1}" -f $totalDeleted, $remaining)
