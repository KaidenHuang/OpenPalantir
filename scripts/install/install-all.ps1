<#
.SYNOPSIS
Installs all components including Redis, Neo4j, front-end and back-end dependencies

.DESCRIPTION
This script calls individual installation scripts for each component
#>

# Force UTF-8 output encoding to prevent garbled text
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$scriptsDir = "$currentDir\scripts\install"

Write-Host "=== Starting OpenPalantir Installation ===" -ForegroundColor Green

# Create necessary directories
Write-Host "1. Creating directory structure..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path "$currentDir\dependencies" -Force | Out-Null
New-Item -ItemType Directory -Path "$currentDir\logs" -Force | Out-Null

# Initialize installation results
$results = @()

# Install Redis
Write-Host "2. Installing Redis..." -ForegroundColor Cyan
$redisResult = & "$scriptsDir\install-redis.ps1"
$results += @{Component="Redis"; Success=$redisResult}

# Install Neo4j
Write-Host "3. Installing Neo4j..." -ForegroundColor Cyan
$neo4jResult = & "$scriptsDir\install-neo4j.ps1"
$results += @{Component="Neo4j"; Success=$neo4jResult}

# Install front-end dependencies
Write-Host "4. Installing Front-end Dependencies..." -ForegroundColor Cyan
$frontendResult = & "$scriptsDir\install-frontend.ps1"
$results += @{Component="Front-end"; Success=$frontendResult}

# Install back-end dependencies
Write-Host "5. Installing Back-end Dependencies..." -ForegroundColor Cyan
$backendResult = & "$scriptsDir\install-backend.ps1"
$results += @{Component="Back-end"; Success=$backendResult}

# Summary
Write-Host "=== Installation Summary ===" -ForegroundColor Green
foreach ($result in $results) {
    if ($result.Success) {
        Write-Host "  $($result.Component): Installed Success" -ForegroundColor Green
    } else {
        Write-Host "  $($result.Component): Installation Failed" -ForegroundColor Red
    }
}

# Check if all installations were successful
$allSuccess = $results | ForEach-Object { $_.Success } | Where-Object { $_ -eq $false } | Measure-Object | Select-Object -ExpandProperty Count

if ($allSuccess -eq 0) {
    Write-Host "=== Installation Complete ===" -ForegroundColor Green
    Write-Host "All components installed successfully!" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Please follow these steps to start the system:" -ForegroundColor Yellow
    Write-Host "1. Run .\scripts\service\start-services.ps1 to start Neo4j and Redis services"
    Write-Host "2. Navigate to backend directory and run:python -m uvicorn main:app --reload to start back-end service"
    Write-Host "3. Navigate to frontend directory and run: npm run dev to start front-end service"
    Write-Host ""
    Write-Host "Default access addresses:" -ForegroundColor Yellow
    Write-Host "- Frontend App: http://127.0.0.1:5175"
    Write-Host "- API Docs: http://127.0.0.1:8000/docs"
    Write-Host "- Neo4j Browser: http://127.0.0.1:7474"
} else {
    Write-Host "=== Installation Complete with Errors ===" -ForegroundColor Red
    Write-Host "Some components failed to install. Please check the output above for details." -ForegroundColor Yellow
}
