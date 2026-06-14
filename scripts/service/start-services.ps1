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
$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$dependenciesDir = "$projectRoot\dependencies"

# Neo4j 5.x: use Windows service management, neo4j.bat only supports install/uninstall
Write-Host "=== Starting OpenPalantir Services ===" -ForegroundColor Green
try {
    $svc = Get-Service -Name "Neo4j" -ErrorAction SilentlyContinue
    if (-not $svc) {
        $svc = Get-Service | Where-Object { $_.DisplayName -eq 'Neo4j' }
    }
    if ($svc) {
        Write-Host "  Starting Neo4j service ($($svc.Name))..."
        if ($svc.Status -ne 'Running') {
            # Service control requires admin privileges, use silent elevation
            $tempBat = [System.IO.Path]::GetTempFileName() + ".bat"
            Set-Content -Path $tempBat -Value "@echo off`r`nnet start `"$($svc.Name)`""
            $tempVbs = [System.IO.Path]::GetTempFileName() + ".vbs"
            Set-Content -Path $tempVbs -Value "CreateObject(""WScript.Shell"").Run ""$tempBat"", 0, True"
            try {
                Start-Process -FilePath "wscript.exe" -ArgumentList "`"$tempVbs`"" -Verb RunAs -Wait
            } finally {
                Remove-Item $tempBat -Force -ErrorAction SilentlyContinue
                Remove-Item $tempVbs -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds 2
            $svc.Refresh()
            if ($svc.Status -eq 'Running') {
                Write-Host "  Neo4j service started" -ForegroundColor Green
            } else {
                Write-Host "  Neo4j service may not have started (status: $($svc.Status))" -ForegroundColor Yellow
            }
        } else {
            Write-Host "  Neo4j service already running"
        }
    } else {
        Write-Host "  Neo4j service not found, skipping..." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Failed to start Neo4j service: $($_.Exception.Message)" -ForegroundColor Red
}

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

# Start Debezium Server (CDC 增量同步)
try {
    $debeziumDir = "$dependenciesDir\debezium\extracted"
    $debeziumBat = "$debeziumDir\run.bat"
    if (Test-Path $debeziumBat) {
        Write-Host "  Starting Debezium Server (CDC)..."
        $debeziumDataDir = "$projectRoot\backend\data\debezium"
        New-Item -ItemType Directory -Path $debeziumDataDir -Force | Out-Null
        $logFile = "$debeziumDataDir\debezium.log"
        $errFile = "$debeziumDataDir\debezium-error.log"
        Start-Process -FilePath $debeziumBat -WorkingDirectory $debeziumDir `
            -RedirectStandardOutput $logFile `
            -RedirectStandardError $errFile `
            -WindowStyle Hidden
        Write-Host "  Debezium Server started in background"
        Write-Host "  Logs: $logFile"
    } else {
        Write-Host "  Debezium Server not found, skipping (CDC incremental sync unavailable)..." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Failed to start Debezium Server, skipping..." -ForegroundColor Yellow
}

Write-Host "=== Services Start Complete ===" -ForegroundColor Green
Write-Host "Please start the back-end and front-end services manually:"
Write-Host "1. Navigate to backend directory and run: python -m uvicorn main:app --reload"
Write-Host "2. Navigate to frontend directory and run: npm run dev"
