<#
.SYNOPSIS
Cleans up back-end dependencies and stops back-end service

.DESCRIPTION
This script stops back-end service and cleans up back-end dependencies and environment files
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
$backendDir = "$projectRoot\backend"
$envFile = "$backendDir\.env"

Initialize-LogFile -Action "uninstall-backend" -LogFilePath $LogFilePath

Write-Host "=== Uninstalling Back-end Dependencies ===" -ForegroundColor Green
Write-Log "Uninstalling back-end dependencies"

# Stop back-end service if running
Write-Host "  Stopping back-end service..."
Write-Log "Stopping back-end service"
$backendProcesses = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    $cmdLine -match "uvicorn" -or $cmdLine -match "main:app"
}

if ($backendProcesses.Count -gt 0) {
    foreach ($process in $backendProcesses) {
        try {
            Stop-Process -Id $process.Id -Force
            Write-Host "  Stopped back-end service process: $($process.Id)" -ForegroundColor Green
            Write-Log "Stopped back-end process PID $($process.Id)"
        } catch {
            Write-Host "  Failed to stop back-end service process: $($process.Id)" -ForegroundColor Yellow
            Write-Log "Failed to stop back-end process PID $($process.Id): $($_.Exception.Message)" -Level WARN
        }
    }
} else {
    Write-Host "  No back-end service process found" -ForegroundColor Yellow
    Write-Log "No back-end service process found"
}

if (Test-Path $backendDir) {
    # Remove environment file
    if (Test-Path $envFile) {
        Write-Host "  Removing environment variables file..."
        Remove-Item -Path $envFile -Force
        Write-Host "  Environment variables file removed" -ForegroundColor Green
        Write-Log "Removed $envFile"
    }

    # Note: We don't remove Python dependencies by default as they're installed globally
    # If you want to remove specific packages, you would need to uninstall them individually
    Write-Host "  Back-end dependencies preserved for future use" -ForegroundColor Yellow
    Write-Log "Back-end uninstallation completed"
    return $true
} else {
    Write-Host "  Back-end directory not found, skipping cleanup" -ForegroundColor Yellow
    Write-Log "Back-end directory not found, skipping" -Level WARN
    return $true
}
