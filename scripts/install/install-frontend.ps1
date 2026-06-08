<#
.SYNOPSIS
Installs front-end dependencies and starts front-end service

.DESCRIPTION
This script installs front-end dependencies, builds the front-end application, and optionally starts the front-end service
#>
# Define parameters
param(
    [switch]$StartService = $false
)

# Set error handling
$ErrorActionPreference = "Stop"

# Force UTF-8 output encoding to prevent garbled text
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Define variables
$currentDir = Get-Location
$dependenciesDir = "$currentDir\dependencies"
$frontendDir = "$currentDir\frontend"

Write-Host "=== Installing Front-end Dependencies ===" -ForegroundColor Green

if (Test-Path $frontendDir) {
    Set-Location $frontendDir
    $localFrontendDir = "$dependenciesDir\frontend\local"
    if (Test-Path $localFrontendDir) {
        Write-Host "  Found local front-end dependencies, using offline installation..."
        if (Test-Path "$localFrontendDir\package.json") {
            # Install front-end dependencies, skipping already installed ones
            Write-Host "  Installing front-end dependencies..."
            npm install --legacy-peer-deps
            Write-Host "  Building front-end..."
            npm run build
        } else {
            Write-Host "  Local front-end package.json not found, trying online installation..." -ForegroundColor Yellow
            Write-Host "  Running npm install..."
            npm install --legacy-peer-deps
            Write-Host "  Building front-end..."
            npm run build
        }
    } else {
        Write-Host "  Running npm install..."
        npm install --legacy-peer-deps
        Write-Host "  Building front-end..."
        npm run build
    }
    
    # Start front-end service if requested
    if ($StartService) {
        Write-Host "  Starting front-end service..." -ForegroundColor Cyan
        Write-Host "  Front-end service will run on http://127.0.0.1:5173"
        Write-Host "  To start the service, navigate to frontend directory and run: npm run dev"
        Write-Host "  Press Ctrl+C to stop the service"
        Write-Host "  Starting service now..."
        npm run dev
    }
    
    Set-Location $currentDir
    Write-Host "  Front-end installation successful!" -ForegroundColor Green
    return $true
} else {
    Write-Host "  Front-end directory not found, skipping front-end dependency installation" -ForegroundColor Yellow
    return $false
}
