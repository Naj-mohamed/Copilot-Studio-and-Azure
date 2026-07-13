param(
    [string]$Rg = "<your-resource-group>",
    [string]$SearchSvc = "<your-search-service>",
    [string]$Index = "sharepoint-index",
    [string]$OutCsv = ".\index-files-report.csv",
    [string]$Subscription = "<your-subscription-id>"
)

$ErrorActionPreference = "Stop"
az account set --subscription $Subscription | Out-Null

$searchKey = az search query-key list --service-name $SearchSvc --resource-group $Rg --query "[0].key" -o tsv
if (-not $searchKey) { throw "Could not retrieve a query key for $SearchSvc" }

$headers = @{ "api-key" = $searchKey; "Content-Type" = "application/json" }
$uri = "https://$SearchSvc.search.windows.net/indexes/$Index/docs/search?api-version=2024-07-01"

$all = New-Object System.Collections.Generic.List[object]
$skip = 0
$total = $null
do {
    $body = @{ search = "*"; count = $true; top = 1000; skip = $skip; select = "title,parent_id,source_url" } | ConvertTo-Json
    $resp = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -Body $body
    if ($null -eq $total) { $total = [int]$resp.'@odata.count' }
    foreach ($d in $resp.value) { $all.Add($d) }
    $skip += 1000
} while ($all.Count -lt $total -and $resp.value.Count -gt 0)

$files = $all | Group-Object parent_id | ForEach-Object {
    [pscustomobject]@{
        Title    = $_.Group[0].title
        Chunks   = $_.Count
        Url      = $_.Group[0].source_url
        ParentId = $_.Name
    }
} | Sort-Object Title

$files | Export-Csv -Path $OutCsv -NoTypeInformation -Encoding UTF8

Write-Host ("Total chunks : {0}" -f $total)
Write-Host ("Unique files : {0}" -f $files.Count)
Write-Host ("CSV written  : {0}" -f $OutCsv)
Write-Host ""
$files | Select-Object Title, Chunks, Url | Format-Table -AutoSize -Wrap
