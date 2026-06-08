<#
.SYNOPSIS
Cleans up back-end dependencies and stops back-end service

.DESCRIPTION
This script stops back-end service and cleans up back-end dependencies and environment files
#>
# Force UTF-8 output encoding to prevent garbled text
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8


# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$backendDir = "$currentDir\backend"
$envFile = "$backendDir\.env"

Write-Host "=== Uninstalling Back-end Dependencies ===" -ForegroundColor Green

# Stop back-end service if running
Write-Host "  Stopping back-end service..."
$backendProcesses = Get-Process | Where-Object {
    $_.ProcessName -eq "python" -and $_.MainWindowTitle -like "*uvicorn*" -or
    $_.ProcessName -eq "python" -and $_.MainWindowTitle -like "*main:app*"
}

if ($backendProcesses.Count -gt 0) {
    foreach ($process in $backendProcesses) {
        try {
            Stop-Process -Id $process.Id -Force
            Write-Host "  Stopped back-end service process: $($process.Id)" -ForegroundColor Green
        } catch {
            Write-Host "  Failed to stop back-end service process: $($process.Id)" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  No back-end service process found" -ForegroundColor Yellow
}

if (Test-Path $backendDir) {
    # Remove environment file
    if (Test-Path $envFile) {
        Write-Host "  Removing environment variables file..."
        Remove-Item -Path $envFile -Force
        Write-Host "  Environment variables file removed" -ForegroundColor Green
    }
    
    # Note: We don't remove Python dependencies by default as they're installed globally
    # If you want to remove specific packages, you would need to uninstall them individually
    Write-Host "  Back-end dependencies preserved for future use" -ForegroundColor Yellow
    return $true
} else {
    Write-Host "  Back-end directory not found, skipping cleanup" -ForegroundColor Yellow
    return $true
}
