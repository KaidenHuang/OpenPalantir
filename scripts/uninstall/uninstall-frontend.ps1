<#
.SYNOPSIS
Cleans up front-end dependencies and stops front-end service

.DESCRIPTION
This script stops front-end service and cleans up front-end dependencies
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
$frontendDir = "$projectRoot\frontend"

Initialize-LogFile -Action "uninstall-frontend" -LogFilePath $LogFilePath

Write-Host "=== Uninstalling Front-end Dependencies ===" -ForegroundColor Green
Write-Log "Uninstalling front-end dependencies"

# Stop front-end service if running
Write-Host "  Stopping front-end service..."
Write-Log "Stopping front-end service"
$frontendProcesses = Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object {
    $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    $cmdLine -match "vite" -or $cmdLine -match "npm.*dev"
}

if ($frontendProcesses.Count -gt 0) {
    foreach ($process in $frontendProcesses) {
        try {
            Stop-Process -Id $process.Id -Force
            Write-Host "  Stopped front-end service process: $($process.Id)" -ForegroundColor Green
            Write-Log "Stopped front-end process PID $($process.Id)"
        } catch {
            Write-Host "  Failed to stop front-end service process: $($process.Id)" -ForegroundColor Yellow
            Write-Log "Failed to stop front-end process PID $($process.Id): $($_.Exception.Message)" -Level WARN
        }
    }
} else {
    Write-Host "  No front-end service process found" -ForegroundColor Yellow
    Write-Log "No front-end service process found"
}

if (Test-Path $frontendDir) {
    # Note: We don't remove node_modules by default to save time for future installations
    # If you want to remove node_modules, uncomment the following lines
    # Write-Host "  Cleaning up front-end node_modules..."
    # Remove-Item -Path "$frontendDir\node_modules" -Recurse -Force -ErrorAction SilentlyContinue
    # Write-Host "  Front-end node_modules cleaned up" -ForegroundColor Green

    Write-Host "  Front-end dependencies preserved for future use" -ForegroundColor Yellow
    Write-Log "Front-end uninstallation completed"
    return $true
} else {
    Write-Host "  Front-end directory not found, skipping cleanup" -ForegroundColor Yellow
    Write-Log "Front-end directory not found, skipping" -Level WARN
    return $true
}
