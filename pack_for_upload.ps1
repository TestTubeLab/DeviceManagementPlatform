# Device Management Platform - Windows Pack Script

Write-Host "=========================================="
Write-Host "  Device Management Platform - Packing"
Write-Host "=========================================="

$projectPath = $PSScriptRoot
$outputFile = "device-platform.zip"

Write-Host "Project: $projectPath"

# Remove old zip
if (Test-Path $outputFile) {
    Remove-Item $outputFile -Force
}

# Create temp dir
$tempDir = Join-Path $env:TEMP "dmp-temp"
if (Test-Path $tempDir) {
    Remove-Item $tempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $tempDir | Out-Null

Write-Host "Copying files..."

# Copy folders
$folders = @("deployment", "device-agent", "docs")
foreach ($folder in $folders) {
    $src = Join-Path $projectPath $folder
    if (Test-Path $src) {
        $dst = Join-Path $tempDir $folder
        Copy-Item -Path $src -Destination $dst -Recurse
        Write-Host "  Copied: $folder"
    }
}

# Copy server WITHOUT media folder
Write-Host "  Copying server (excluding media)..."
$serverSrc = Join-Path $projectPath "server"
$serverDst = Join-Path $tempDir "server"
New-Item -ItemType Directory -Path $serverDst | Out-Null
Get-ChildItem -Path $serverSrc | Where-Object { $_.Name -notin @("media", "staticfiles", "db.sqlite3") } | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $serverDst -Recurse
}
Write-Host "  Copied: server"

# Copy frontend WITHOUT node_modules
Write-Host "  Copying frontend (excluding node_modules)..."
$frontendSrc = Join-Path $projectPath "frontend"
$frontendDst = Join-Path $tempDir "frontend"
New-Item -ItemType Directory -Path $frontendDst | Out-Null

# Copy frontend files except node_modules
Get-ChildItem -Path $frontendSrc | Where-Object { $_.Name -ne "node_modules" } | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $frontendDst -Recurse
}
Write-Host "  Copied: frontend"

# Copy single files
$files = @("requirements.txt", "README.md", "CLOUD_DEPLOY_GUIDE.md")
foreach ($file in $files) {
    $src = Join-Path $projectPath $file
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $tempDir
    }
}

# Remove unnecessary folders recursively
Write-Host "Cleaning __pycache__ and .git..."
Get-ChildItem -Path $tempDir -Recurse -Directory -Force | Where-Object { $_.Name -in @("__pycache__", ".git", "staticfiles") } | ForEach-Object {
    Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
}

# Remove db.sqlite3
Get-ChildItem -Path $tempDir -Recurse -File -Filter "db.sqlite3" | Remove-Item -Force -ErrorAction SilentlyContinue

# Create zip
Write-Host "Creating zip..."
Compress-Archive -Path (Join-Path $tempDir "*") -DestinationPath $outputFile -Force

# Cleanup temp
Remove-Item $tempDir -Recurse -Force

# Show result
$size = [math]::Round((Get-Item $outputFile).Length / 1MB, 2)
Write-Host ""
Write-Host "=========================================="
Write-Host "  Done! File: $outputFile ($size MB)"
Write-Host "=========================================="
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Upload: scp $outputFile root@YOUR_SERVER_IP:~/"
Write-Host "2. On server:"
Write-Host "   unzip $outputFile -d DeviceManagementPlatform"
Write-Host "   cd DeviceManagementPlatform/deployment/deploy-simple"
Write-Host "   chmod +x deploy.sh entrypoint.sh"
Write-Host "   ./deploy.sh 8081"
