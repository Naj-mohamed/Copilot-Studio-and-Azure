param(
    [string]$Subscription = "<your-subscription-id>",
    [string]$App = "<your-function-app-name>"
)

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$stage = Join-Path $env:TEMP "spc_deploy"
$zip = Join-Path $env:TEMP "spc_deploy.zip"

az account set --subscription $Subscription | Out-Null

# Stage runtime files only
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

Copy-Item (Join-Path $src "*.py") $stage
Copy-Item (Join-Path $src "host.json") $stage
Copy-Item (Join-Path $src "requirements.txt") $stage
if (Test-Path (Join-Path $src ".funcignore")) { Copy-Item (Join-Path $src ".funcignore") $stage }
if (Test-Path (Join-Path $src ".python_packages")) { } # skip

# Remove caches/tests that may have been copied via *.py glob (none expected at root)
Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Write-Host "Zip built:" (Get-Item $zip).Length "bytes"

# Get ARM token for SCM OneDeploy
$token = az account get-access-token --resource https://management.azure.com --query accessToken -o tsv
$uri = "https://$App.scm.azurewebsites.net/api/publish?RemoteBuild=true"
$headers = @{ Authorization = "Bearer $token" }

Write-Host "POSTing to $uri ..."
$resp = Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -InFile $zip -ContentType "application/zip"
Write-Host "Deploy submitted."

# Poll deployment status
$statusUri = "https://$App.scm.azurewebsites.net/api/deployments/latest"
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 8
    try {
        $d = Invoke-RestMethod -Uri $statusUri -Method Get -Headers $headers
        Write-Host ("[{0}] status={1} progress='{2}'" -f $i, $d.status, $d.progress)
        if ($d.status -eq 4) { Write-Host "SUCCESS id=$($d.id)"; break }
        if ($d.status -eq 3) { Write-Host "FAILED id=$($d.id)"; $d | ConvertTo-Json -Depth 5; break }
    } catch {
        Write-Host "poll error: $($_.Exception.Message)"
    }
}
