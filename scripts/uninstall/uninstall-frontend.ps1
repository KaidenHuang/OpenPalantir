<#
.SYNOPSIS
Cleans up front-end dependencies and stops front-end service

.DESCRIPTION
This script stops front-end service and cleans up front-end dependencies
#>

# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$frontendDir = "$currentDir\frontend"

Write-Host "=== Uninstalling Front-end Dependencies ===" -ForegroundColor Green

# Stop front-end service if running
Write-Host "  Stopping front-end service..."
$frontendProcesses = Get-Process | Where-Object {
    $_.ProcessName -eq "node" -and $_.MainWindowTitle -like "*Vite*" -or
    $_.ProcessName -eq "npm" -and $_.MainWindowTitle -like "*dev*"
}

if ($frontendProcesses.Count -gt 0) {
    foreach ($process in $frontendProcesses) {
        try {
            Stop-Process -Id $process.Id -Force
            Write-Host "  Stopped front-end service process: $($process.Id)" -ForegroundColor Green
        } catch {
            Write-Host "  Failed to stop front-end service process: $($process.Id)" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  No front-end service process found" -ForegroundColor Yellow
}

if (Test-Path $frontendDir) {
    # Note: We don't remove node_modules by default to save time for future installations
    # If you want to remove node_modules, uncomment the following lines
    # Write-Host "  Cleaning up front-end node_modules..."
    # Remove-Item -Path "$frontendDir\node_modules" -Recurse -Force -ErrorAction SilentlyContinue
    # Write-Host "  Front-end node_modules cleaned up" -ForegroundColor Green
    
    Write-Host "  Front-end dependencies preserved for future use" -ForegroundColor Yellow
    return $true
} else {
    Write-Host "  Front-end directory not found, skipping cleanup" -ForegroundColor Yellow
    return $true
}
