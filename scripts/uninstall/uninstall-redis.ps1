<#
.SYNOPSIS
Uninstalls Redis service and cleans up extracted files

.DESCRIPTION
This script stops and uninstalls Redis service and removes extracted files
#>

# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$dependenciesDir = "$currentDir\dependencies"
$redisDir = "$dependenciesDir\redis"
$extractDir = "$redisDir\extracted"

Write-Host "=== Uninstalling Redis ===" -ForegroundColor Green

# Stop Redis service
Write-Host "  Stopping Redis service..."
try {
    $redisServerExe = Get-ChildItem -Path $extractDir -Recurse -Name "redis-server.exe" | Select-Object -First 1
    if ($redisServerExe) {
        $redisServerPath = "$extractDir\$redisServerExe"
        & "$redisServerPath" --service-stop
        & "$redisServerPath" --service-uninstall
        Write-Host "  Redis service stopped and uninstalled successfully" -ForegroundColor Green
    } else {
        Write-Host "  Redis server executable not found, skipping service stop" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Failed to stop Redis service: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Clean up extracted directory
Write-Host "  Cleaning up Redis extracted directory..."
try {
    if (Test-Path $extractDir) {
        Remove-Item -Path $extractDir -Recurse -Force
        Write-Host "  Redis extracted directory cleaned up successfully" -ForegroundColor Green
        return $true
    } else {
        Write-Host "  Redis extracted directory not found, skipping cleanup" -ForegroundColor Yellow
        return $true
    }
} catch {
    Write-Host "  Failed to clean up Redis extracted directory: $($_.Exception.Message)" -ForegroundColor Red
    return $false
}
