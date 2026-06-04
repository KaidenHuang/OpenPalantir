<#
.SYNOPSIS
Uninstalls all components including Redis, Neo4j, front-end and back-end dependencies

.DESCRIPTION
This script calls individual uninstallation scripts for each component
#>

# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$scriptsDir = "$currentDir\scripts\uninstall"

Write-Host "=== Starting OpenPalantir Uninstallation ===" -ForegroundColor Green

# Initialize uninstallation results
$results = @()

# Uninstall Redis
Write-Host "1. Uninstalling Redis..." -ForegroundColor Cyan
$redisResult = & "$scriptsDir\uninstall-redis.ps1"
$results += @{Component="Redis"; Success=$redisResult}

# Uninstall Neo4j
Write-Host "2. Uninstalling Neo4j..." -ForegroundColor Cyan
$neo4jResult = & "$scriptsDir\uninstall-neo4j.ps1"
$results += @{Component="Neo4j"; Success=$neo4jResult}

# Uninstall front-end dependencies
Write-Host "3. Uninstalling Front-end Dependencies..." -ForegroundColor Cyan
$frontendResult = & "$scriptsDir\uninstall-frontend.ps1"
$results += @{Component="Front-end"; Success=$frontendResult}

# Uninstall back-end dependencies
Write-Host "4. Uninstalling Back-end Dependencies..." -ForegroundColor Cyan
$backendResult = & "$scriptsDir\uninstall-backend.ps1"
$results += @{Component="Back-end"; Success=$backendResult}

# Clean up logs directory
Write-Host "5. Cleaning up logs directory..." -ForegroundColor Cyan
try {
    if (Test-Path "$currentDir\logs") {
        Remove-Item -Path "$currentDir\logs" -Recurse -Force
        Write-Host "  Logs directory cleaned up successfully" -ForegroundColor Green
    } else {
        Write-Host "  Logs directory not found, skipping cleanup" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Failed to clean up logs directory: $($_.Exception.Message)" -ForegroundColor Red
}

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
$allSuccess = $results | ForEach-Object { $_.Success } | Where-Object { $_ -eq $false } | Measure-Object | Select-Object -ExpandProperty Count

if ($allSuccess -eq 0) {
    Write-Host "=== Uninstallation Complete ===" -ForegroundColor Green
    Write-Host "All components uninstalled successfully!" -ForegroundColor Yellow
} else {
    Write-Host "=== Uninstallation Complete with Errors ===" -ForegroundColor Red
    Write-Host "Some components failed to uninstall. Please check the output above for details." -ForegroundColor Yellow
}
