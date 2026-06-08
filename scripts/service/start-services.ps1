<#
.SYNOPSIS
Starts OpenPalantir services including Neo4j and Redis

.DESCRIPTION
This script starts the Neo4j and Redis services required for OpenPalantir
#>
# Force UTF-8 output encoding to prevent garbled text
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8


# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$dependenciesDir = "$currentDir\dependencies"

Write-Host "=== Starting OpenPalantir Services ===" -ForegroundColor Green

# Function to start a service
function Start-ServiceIfExists {
    param(
        [string]$serviceName,
        [string]$searchPath,
        [string]$executableName,
        [string]$command,
        [string[]]$arguments
    )
    
    try {
        $executable = Get-ChildItem -Path $searchPath -Recurse -Name $executableName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($executable) {
            $executablePath = Join-Path $searchPath $executable
            $executableDir = Split-Path $executablePath -Parent
            
            Write-Host "  Starting $serviceName service..."
            Write-Host "  Executable path: $executablePath"
            Write-Host "  Executable directory: $executableDir"
            
            if (Test-Path $executablePath) {
                Write-Host "  Executable found at: $executablePath"
                Set-Location $executableDir
                try {
                    Write-Host "  Running command: $command $($arguments -join ' ' )"
                    & $command $arguments
                } finally {
                    Set-Location $currentDir
                }
            } else {
                Write-Host "  Executable not found at: $executablePath" -ForegroundColor Red
            }
        } else {
            Write-Host "  $serviceName executable not found, skipping..." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  Failed to start $serviceName service: $($_.Exception.Message)" -ForegroundColor Red
        Set-Location $currentDir
    }
}

# Start Neo4j
Start-ServiceIfExists -serviceName "Neo4j" -searchPath "$dependenciesDir\neo4j" -executableName "neo4j.bat" -command ".\neo4j.bat" -arguments @("start")

# Start Redis
try {
    $redisExe = Get-ChildItem -Path "$dependenciesDir\redis" -Recurse -Name "redis-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($redisExe) {
        $redisPath = "$dependenciesDir\redis\$redisExe"
        Write-Host "  Starting Redis service..."
        & "$redisPath" --service-start
    } else {
        Write-Host "  Redis executable not found, skipping..." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Failed to start Redis service, skipping..." -ForegroundColor Yellow
}

Write-Host "=== Services Start Complete ===" -ForegroundColor Green
Write-Host "Please start the back-end and front-end services manually:"
Write-Host "1. Navigate to backend directory and run: python -m uvicorn main:app --reload"
Write-Host "2. Navigate to frontend directory and run: npm run dev"
