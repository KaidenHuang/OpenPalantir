<#
.SYNOPSIS
Uninstalls Redis service and cleans up extracted files

.DESCRIPTION
This script stops and uninstalls Redis service and removes extracted files
#>
param(
    [string]$LogFilePath
)

# Force UTF-8 output encoding to prevent garbled text
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8


# Set error handling
$ErrorActionPreference = "Stop"

# Load logging helpers
. "$PSScriptRoot\..\install-uninstall-helpers.ps1"

# Define variables
$currentDir = Get-Location
$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$dependenciesDir = "$projectRoot\dependencies"
$redisDir = "$dependenciesDir\redis"
$extractDir = "$redisDir\extracted"

Initialize-LogFile -Action "uninstall-redis" -LogFilePath $LogFilePath

Write-Host "=== Uninstalling Redis ===" -ForegroundColor Green
Write-Log "Uninstalling Redis"

# Stop Redis service
Write-Host "  Stopping Redis service..."
Write-Log "Stopping Redis service"
try {
    $redisServerExe = Get-ChildItem -Path $extractDir -Recurse -Name "redis-server.exe" | Select-Object -First 1
    if ($redisServerExe) {
        $redisServerPath = "$extractDir\$redisServerExe"
        Write-Log "Running redis-server.exe --service-stop"
        $exitCode = Invoke-LoggedProcess -FilePath $redisServerPath -ArgumentList @("--service-stop") -UseCmdShell
        Write-Log "Running redis-server.exe --service-uninstall"
        $exitCode = Invoke-LoggedProcess -FilePath $redisServerPath -ArgumentList @("--service-uninstall") -UseCmdShell
        Write-Host "  Redis service stopped and uninstalled successfully" -ForegroundColor Green
        Write-Log "Redis service stopped and uninstalled"
    } else {
        Write-Host "  Redis server executable not found, skipping service stop" -ForegroundColor Yellow
        Write-Log "redis-server.exe not found in $extractDir, skipping service stop" -Level WARN
    }
} catch {
    Write-Host "  Failed to stop Redis service: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Log "Failed to stop Redis service: $($_.Exception.Message)" -Level ERROR
}

# Clean up extracted directory
Write-Host "  Cleaning up Redis extracted directory..."
Write-Log "Cleaning up Redis extracted directory: $extractDir"
try {
    if (Test-Path $extractDir) {
        Remove-Item -Path $extractDir -Recurse -Force
        Write-Host "  Redis extracted directory cleaned up successfully" -ForegroundColor Green
        Write-Log "Removed $extractDir"
        return $true
    } else {
        Write-Host "  Redis extracted directory not found, skipping cleanup" -ForegroundColor Yellow
        Write-Log "Redis extracted directory not found, skipping"
        return $true
    }
} catch {
    Write-Host "  Failed to clean up Redis extracted directory: $($_.Exception.Message)" -ForegroundColor Red
    Write-Log "Failed to remove ${extractDir}: $($_.Exception.Message)" -Level ERROR
    return $false
}
