<#
.SYNOPSIS
    Finds approved SharePoint files that are NOT present in the Azure AI Search index.

.DESCRIPTION
    Enumerates every file in the configured SharePoint document library that matches the
    connector's metadata filter (e.g. DDStatus=Approved and FileLeafRef<>"Main Document.docx"),
    computes each file's deterministic parent_id (the same SHA-256 scheme the connector uses),
    and compares that set against the parent_ids actually stored in the search index.

    Any approved file whose parent_id is missing from the index is written to a CSV together
    with a best-effort reason (size over limit, likely empty extraction, video, etc.).

    The script is READ-ONLY. It never writes to SharePoint, the index, or the function app.

.PREREQUISITES
    1. Azure CLI installed and signed in to the correct tenant.
    2. A Microsoft Graph token with the Sites.Read.All (or Sites.Read) delegated permission,
       OR an app token passed via -GraphToken. If your current login lacks the scope, run:

           az login --scope "https://graph.microsoft.com/Sites.Read.All" --tenant <tenantId>

    3. Reader access to the Azure AI Search service (to retrieve the admin key), OR pass the
       key directly with -SearchAdminKey.

.EXAMPLE
    # Uses the defaults baked in below (this environment)
    ./find-unindexed-approved-files.ps1

.EXAMPLE
    # Override for a different environment / library
    ./find-unindexed-approved-files.ps1 `
        -SubscriptionId "<sub>" -TenantId "<tenant>" `
        -SiteUrl "https://contoso.sharepoint.com/sites/Policies" `
        -LibraryName "Shared Documents" `
        -SearchService "my-search" -SearchResourceGroup "my-rg" -IndexName "sharepoint-index" `
        -MetadataFilters 'DDStatus=Approved,FileLeafRef<>"Main Document.docx"' `
        -MaxFileSizeMB 500 -OutputCsv "./unindexed.csv"

.NOTES
    The "Reason" column is best-effort. The index only stores a parent_id (a hash), so the exact
    per-file failure cause is inferred from file size and extension. For the authoritative cause,
    correlate the file with the function app's Application Insights traces.
#>

[CmdletBinding()]
param(
    [string]$SubscriptionId   = "<your-subscription-id>",
    [string]$TenantId         = "<your-tenant-id>",

    [string]$SiteUrl          = "https://contoso.sharepoint.com/sites/YourSite",
    [string]$LibraryName      = "Shared Documents",

    [string]$SearchService    = "<your-search-service>",
    [string]$SearchResourceGroup = "<your-resource-group>",
    [string]$IndexName        = "sharepoint-index",
    [string]$SearchApiVersion = "2024-07-01",

    # Same syntax as the connector's METADATA_FILTERS app setting.
    # Operators: "=" (equals) and "<>" (not-equals). Values may be quoted. Case-insensitive.
    [string]$MetadataFilters  = 'DDStatus=Approved,FileLeafRef<>"Main Document.docx"',

    [int]$MaxFileSizeMB       = 500,

    [string]$OutputCsv        = "./unindexed-approved-files.csv",

    # Optional: supply tokens/keys directly to skip the az lookups.
    [string]$GraphToken       = "",
    [string]$SearchAdminKey   = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Warn2($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }

# ---------------------------------------------------------------------------
# 0. Locate az and set subscription
# ---------------------------------------------------------------------------
$azWin = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin"
if (Test-Path $azWin) { $env:PATH = "$azWin;" + $env:PATH }
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI ('az') was not found on PATH. Install it or add it to PATH."
}
if ($SubscriptionId) {
    az account set --subscription $SubscriptionId 2>&1 | Out-Null
}

# ---------------------------------------------------------------------------
# 1. Parse the metadata filter (mirrors the connector's parser)
#    Each condition is (column, op, value); op is "=" or "<>".
# ---------------------------------------------------------------------------
function Parse-MetadataFilters([string]$raw) {
    $conds = @()
    if ([string]::IsNullOrWhiteSpace($raw)) { return $conds }
    foreach ($part in $raw.Split(",")) {
        $p = $part.Trim()
        if ($p -eq "") { continue }
        if ($p -match '^(?<col>[^=<>]+?)\s*(?<op><>|=)\s*(?<val>.*)$') {
            $col = $Matches['col'].Trim()
            $op  = $Matches['op']
            $val = $Matches['val'].Trim().Trim('"').Trim("'")
            $conds += [pscustomobject]@{ Column = $col; Op = $op; Value = $val }
        } else {
            Write-Warn2 "Could not parse filter condition: '$p' (ignored)"
        }
    }
    return $conds
}

$filters = Parse-MetadataFilters $MetadataFilters
Write-Step ("Metadata filter conditions: " + ($filters | ForEach-Object { "$($_.Column) $($_.Op) '$($_.Value)'" } | Join-String -Separator "; "))
$selectCols = ($filters | ForEach-Object { $_.Column }) -join ","
if (-not $selectCols) { $selectCols = "FileLeafRef" }

function Test-MetadataMatch($fields) {
    foreach ($c in $filters) {
        $actual = ""
        if ($fields -and $fields.PSObject.Properties[$c.Column]) {
            $actual = [string]$fields.$($c.Column)
        }
        $equal = ($actual.Trim().ToLower() -eq $c.Value.ToLower())
        if ($c.Op -eq "<>") { if ($equal) { return $false } }
        else                { if (-not $equal) { return $false } }
    }
    return $true
}

# ---------------------------------------------------------------------------
# 2. Acquire a Microsoft Graph token
# ---------------------------------------------------------------------------
if (-not $GraphToken) {
    Write-Step "Acquiring Microsoft Graph token via Azure CLI..."
    $GraphToken = az account get-access-token --resource "https://graph.microsoft.com" --tenant $TenantId --query accessToken -o tsv
}
if (-not $GraphToken) { throw "Failed to acquire a Graph token." }

# Warn early if the delegated token lacks a Sites scope (app tokens use roles, not scp).
try {
    $payloadSeg = $GraphToken.Split('.')[1]
    $pad = $payloadSeg.PadRight($payloadSeg.Length + (4 - $payloadSeg.Length % 4) % 4, '=')
    $claims = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($pad.Replace('-','+').Replace('_','/'))) | ConvertFrom-Json
    $scp = [string]$claims.scp
    $roles = @($claims.roles) -join " "
    if ($scp -and ($scp -notmatch "Sites\.")) {
        Write-Warn2 "Graph token scopes do not include a Sites.* permission (scp='$scp')."
        Write-Warn2 "If enumeration returns 0 drives/403, run:"
        Write-Warn2 "    az login --scope `"https://graph.microsoft.com/Sites.Read.All`" --tenant $TenantId"
    }
} catch { }

$gh = @{ Authorization = "Bearer $GraphToken" }

function Invoke-Graph([string]$url) {
    $attempt = 0
    while ($true) {
        try { return Invoke-RestMethod -Uri $url -Headers $gh -Method Get }
        catch {
            $status = $null
            if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
            if (($status -eq 429 -or $status -ge 500) -and $attempt -lt 5) {
                $attempt++; Start-Sleep -Seconds ([Math]::Min(30, [Math]::Pow(2, $attempt))); continue
            }
            throw
        }
    }
}

# ---------------------------------------------------------------------------
# 3. Resolve site -> drive (document library)
# ---------------------------------------------------------------------------
Write-Step "Resolving SharePoint site and library '$LibraryName'..."
$u = [System.Uri]$SiteUrl
$site = Invoke-Graph "https://graph.microsoft.com/v1.0/sites/$($u.Host):$($u.AbsolutePath)"
$siteId = $site.id
Write-Host "    Site id: $siteId"

$driveId = $null
$drivesUrl = "https://graph.microsoft.com/v1.0/sites/$siteId/drives?`$select=id,name"
while ($drivesUrl) {
    $dp = Invoke-Graph $drivesUrl
    foreach ($d in $dp.value) { if ($d.name -eq $LibraryName) { $driveId = $d.id } }
    $drivesUrl = $dp.'@odata.nextLink'
}
if (-not $driveId) {
    throw "Library '$LibraryName' not found on the site (or the token cannot read its drives). " +
          "Ensure the token has Sites.Read.All and that the library name is exact."
}
Write-Host "    Drive id: $driveId"

# ---------------------------------------------------------------------------
# 4. Recursively enumerate files that match the metadata filter
# ---------------------------------------------------------------------------
Write-Step "Enumerating approved files (this can take a few minutes for large libraries)..."
$sha = [System.Security.Cryptography.SHA256]::Create()
function Get-ParentId([string]$did, [string]$iid) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes("$($did):$($iid)")
    (($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join "").Substring(0, 32)
}

# Turn a Graph parentReference.path like "/drives/<id>/root:/Reports/Sub" into a
# clean, library-relative folder path such as "/Reports/Sub".
function Get-FolderPath($item) {
    $raw = ""
    if ($item.parentReference -and $item.parentReference.path) { $raw = [string]$item.parentReference.path }
    if ($raw -match 'root:(?<rel>.*)$') { $rel = $Matches['rel'] } else { $rel = $raw }
    if ([string]::IsNullOrEmpty($rel)) { $rel = "/" }
    try { $rel = [System.Uri]::UnescapeDataString($rel) } catch { }
    return $rel
}

$expand = "`$expand=listItem(`$expand=fields(`$select=$selectCols))"
$approved = @{}   # parent_id -> file object
$folders = New-Object System.Collections.Queue
$folders.Enqueue("root")
$scanned = 0
while ($folders.Count -gt 0) {
    $fid = $folders.Dequeue()
    if ($fid -eq "root") {
        $url = "https://graph.microsoft.com/v1.0/drives/$driveId/root/children?$expand&`$top=200"
    } else {
        $url = "https://graph.microsoft.com/v1.0/drives/$driveId/items/$fid/children?$expand&`$top=200"
    }
    while ($url) {
        $resp = Invoke-Graph $url
        foreach ($item in $resp.value) {
            if ($item.folder) {
                $folders.Enqueue($item.id)
            } elseif ($item.file) {
                $fields = $null
                if ($item.listItem) { $fields = $item.listItem.fields }
                if (-not (Test-MetadataMatch $fields)) { continue }
                $pid2 = Get-ParentId $driveId $item.id
                $approved[$pid2] = [pscustomobject]@{
                    Name   = $item.name
                    Size   = [int64]$item.size
                    Folder = Get-FolderPath $item
                    Url    = $item.webUrl
                    Parent = $pid2
                }
                $scanned++
                if ($scanned % 250 -eq 0) { Write-Host "    ...matched $scanned files so far" }
            }
        }
        $url = $resp.'@odata.nextLink'
    }
}
Write-Host "    Approved files matching filter: $($approved.Count)" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 5. Load parent_ids already present in the search index
# ---------------------------------------------------------------------------
Write-Step "Reading indexed parent_ids from search service '$SearchService'..."
if (-not $SearchAdminKey) {
    $SearchAdminKey = az search admin-key show --service-name $SearchService --resource-group $SearchResourceGroup --query primaryKey -o tsv
}
if (-not $SearchAdminKey) { throw "Could not obtain a search admin key. Pass -SearchAdminKey explicitly." }

$searchUrl = "https://$SearchService.search.windows.net/indexes/$IndexName/docs/search?api-version=$SearchApiVersion"
$sh = @{ "api-key" = $SearchAdminKey; "Content-Type" = "application/json" }
$indexed = New-Object System.Collections.Generic.HashSet[string]
$skip = 0
while ($true) {
    $body = @{ search = "*"; select = "parent_id"; top = 1000; skip = $skip } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri $searchUrl -Method Post -Headers $sh -Body $body
    if (-not $r.value -or $r.value.Count -eq 0) { break }
    foreach ($d in $r.value) { if ($d.parent_id) { [void]$indexed.Add([string]$d.parent_id) } }
    $skip += $r.value.Count
    if ($r.value.Count -lt 1000) { break }
    if ($skip -ge 200000) { break }
}
Write-Host "    Distinct indexed files (parent_id): $($indexed.Count)" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 6. Diff and attribute a best-effort reason
# ---------------------------------------------------------------------------
Write-Step "Computing the missing (approved but not indexed) set..."
$videoExt = @(".mp4", ".mov", ".avi", ".wmv", ".m4v", ".mkv", ".webm")
$rows = @()
foreach ($pid2 in $approved.Keys) {
    if ($indexed.Contains($pid2)) { continue }
    $f = $approved[$pid2]
    $name = $f.Name
    $ext = ""
    if ($name.Contains(".")) { $ext = "." + $name.Substring($name.LastIndexOf(".") + 1).ToLower() }
    $sizeBytes = [int64]$f.Size
    $sizeMB = [math]::Round($sizeBytes / 1MB, 2)
    $folder = $f.Folder
    $relPath = ($folder.TrimEnd('/') + '/' + $name)

    if ($f.Size -gt ($MaxFileSizeMB * 1MB)) {
        $reason = "File is $sizeMB MB, exceeds MAX_FILE_SIZE_MB ($MaxFileSizeMB MB) - skipped before download"
    } elseif ($videoExt -contains $ext) {
        $reason = "Video - produced no transcript blocks (empty/failed transcription) or over size limit"
    } elseif ($ext -eq ".vsd" -or $ext -eq ".vsdx") {
        $reason = "Visio diagram - no text/image content extracted"
    } else {
        $reason = "No content extracted (empty/scanned/unsupported) OR processing timeout (>30 min) - check App Insights for exact cause"
    }

    $rows += [pscustomobject]@{
        FileName  = $name
        FolderPath = $folder
        RelativePath = $relPath
        Extension = $ext
        SizeMB    = $sizeMB
        SizeBytes = $sizeBytes
        Reason    = $reason
        Url       = $f.Url
        ParentId  = $pid2
    }
}
$rows = $rows | Sort-Object FolderPath, FileName

# ---------------------------------------------------------------------------
# 7. Write CSV + summary
# ---------------------------------------------------------------------------
$rows | Export-Csv -Path $OutputCsv -NoTypeInformation -Encoding UTF8
$full = (Resolve-Path $OutputCsv).Path

Write-Host ""
Write-Host "==================== RESULT ====================" -ForegroundColor Green
Write-Host ("Approved files (filter matched): {0}" -f $approved.Count)
Write-Host ("Indexed files (distinct):        {0}" -f $indexed.Count)
Write-Host ("Missing (approved, not indexed): {0}" -f $rows.Count) -ForegroundColor Yellow
Write-Host ("CSV written to:                  {0}" -f $full)
Write-Host "-----------------------------------------------"
Write-Host "Breakdown by reason:"
$rows | Group-Object Reason | Sort-Object Count -Descending | ForEach-Object {
    Write-Host ("  {0,5} x {1}" -f $_.Count, $_.Name)
}
Write-Host "==============================================="
