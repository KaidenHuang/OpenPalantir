<#
.SYNOPSIS
Uninstalls all components including Redis, Neo4j, Debezium, front-end and back-end dependencies

.DESCRIPTION
This script calls individual uninstallation scripts for each component
#>
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
$scriptsDir = "$projectRoot\scripts\uninstall"

Write-Host "=== Starting OpenPalantir Uninstallation ===" -ForegroundColor Green

# Initialize centralized log file
Initialize-LogFile -Action "uninstall"
Write-Host "  Log file: $script:LogFilePath" -ForegroundColor DarkGray

# Initialize uninstallation results
$results = @()

# Uninstall Redis
Write-Host "1. Uninstalling Redis..." -ForegroundColor Cyan
$redisResult = & "$scriptsDir\uninstall-redis.ps1" -LogFilePath $script:LogFilePath
$results += @{Component="Redis"; Success=$redisResult}

# Uninstall Neo4j
Write-Host "2. Uninstalling Neo4j..." -ForegroundColor Cyan
$neo4jResult = & "$scriptsDir\uninstall-neo4j.ps1" -LogFilePath $script:LogFilePath
$results += @{Component="Neo4j"; Success=$neo4jResult}

# Uninstall Debezium
Write-Host "3. Uninstalling Debezium..." -ForegroundColor Cyan
$debeziumResult = & "$scriptsDir\uninstall-debezium.ps1" -LogFilePath $script:LogFilePath
$results += @{Component="Debezium"; Success=$debeziumResult}

# Uninstall front-end Dependencies
Write-Host "4. Uninstalling Front-end Dependencies..." -ForegroundColor Cyan
$frontendResult = & "$scriptsDir\uninstall-frontend.ps1" -LogFilePath $script:LogFilePath
$results += @{Component="Front-end"; Success=$frontendResult}

# Uninstall back-end dependencies
Write-Host "5. Uninstalling Back-end Dependencies..." -ForegroundColor Cyan
$backendResult = & "$scriptsDir\uninstall-backend.ps1" -LogFilePath $script:LogFilePath
$results += @{Component="Back-end"; Success=$backendResult}

# Summary
Write-Host "=== Uninstallation Summary ===" -ForegroundColor Green
foreach ($result in $results) {
    if ($result.Success) {
        Write-Host "  $($result.Component): Uninstalled Success" -ForegroundColor Green
    } else {
        Write-Host "  $($result.Component): Uninstallation Failed" -ForegroundColor Red
    }
}

# Check if all uninstallations were successful
$failureCount = $results | ForEach-Object { $_.Success } | Where-Object { $_ -eq $false } | Measure-Object | Select-Object -ExpandProperty Count

if ($failureCount -eq 0) {
    Write-Host "=== Uninstallation Complete ===" -ForegroundColor Green
    Write-Host "All components uninstalled successfully!" -ForegroundColor Yellow
    Write-Log "Uninstallation completed successfully"
} else {
    Write-Host "=== Uninstallation Complete with Errors ===" -ForegroundColor Red
    Write-Host "Some components failed to uninstall. Please check the log for details:" -ForegroundColor Yellow
    Write-Host "  $script:LogFilePath" -ForegroundColor Yellow
    Write-Log "Uninstallation completed with errors" -Level ERROR
}

# Clean up logs directory (preserve the current log file)
Write-Host "6. Cleaning up old log files..." -ForegroundColor Cyan
try {
    if (Test-Path "$projectRoot\logs") {
        $currentLog = $script:LogFilePath
        Get-ChildItem -Path "$projectRoot\logs" -File | Where-Object { $_.FullName -ne $currentLog } | Remove-Item -Force -ErrorAction SilentlyContinue
        Write-Host "  Old log files cleaned up (current log preserved)" -ForegroundColor Green
    }
} catch {
    Write-Host "  Failed to clean up old log files: $($_.Exception.Message)" -ForegroundColor Red
}
