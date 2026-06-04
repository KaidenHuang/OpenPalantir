<#
.SYNOPSIS
Stops OpenPalantir services including Neo4j and Redis

.DESCRIPTION
This script stops the Neo4j and Redis services used by OpenPalantir
#>

# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$dependenciesDir = "$currentDir\dependencies"

Write-Host "=== Stopping OpenPalantir Services ===" -ForegroundColor Green

# Function to stop a service
function Stop-ServiceIfExists {
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
            
            Write-Host "  Stopping $serviceName service..."
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
        Write-Host "  Failed to stop $serviceName service: $($_.Exception.Message)" -ForegroundColor Red
        Set-Location $currentDir
    }
}

# Stop Neo4j
Stop-ServiceIfExists -serviceName "Neo4j" -searchPath "$dependenciesDir\neo4j" -executableName "neo4j.bat" -command ".\neo4j.bat" -arguments @("stop")

# Stop Redis
try {
    $redisExe = Get-ChildItem -Path "$dependenciesDir\redis" -Recurse -Name "redis-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($redisExe) {
        $redisPath = "$dependenciesDir\redis\$redisExe"
        Write-Host "  Stopping Redis service..."
        & "$redisPath" --service-stop
    } else {
        Write-Host "  Redis executable not found, skipping..." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Failed to stop Redis service, skipping..." -ForegroundColor Yellow
}

Write-Host "=== Services Stop Complete ===" -ForegroundColor Green
Write-Host "Please stop the back-end and front-end services manually if they are running."
