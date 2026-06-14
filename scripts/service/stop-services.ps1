<#
.SYNOPSIS
Stops OpenPalantir services including Neo4j and Redis

.DESCRIPTION
This script stops the Neo4j and Redis services used by OpenPalantir
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
Write-Host "=== Stopping OpenPalantir Services ===" -ForegroundColor Green
try {
    $svc = Get-Service -Name "Neo4j" -ErrorAction SilentlyContinue
    if (-not $svc) {
        $svc = Get-Service | Where-Object { $_.DisplayName -eq 'Neo4j' }
    }
    if ($svc) {
        Write-Host "  Stopping Neo4j service ($($svc.Name))..."
        if ($svc.Status -eq 'Running') {
            # Service control requires admin privileges, use silent elevation
            $tempBat = [System.IO.Path]::GetTempFileName() + ".bat"
            Set-Content -Path $tempBat -Value "@echo off`r`nnet stop `"$($svc.Name)`""
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
            Write-Host "  Neo4j service stopped" -ForegroundColor Green
        } else {
            Write-Host "  Neo4j service not running (status: $($svc.Status))"
        }
    } else {
        Write-Host "  Neo4j service not found, skipping..." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Failed to stop Neo4j service: $($_.Exception.Message)" -ForegroundColor Red
}

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

# Stop Debezium Server (CDC)
try {
    $debeziumProcesses = Get-Process -Name "java" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "debezium-server" -or $_.CommandLine -match "io\.debezium\.server"
    }
    if ($debeziumProcesses) {
        Write-Host "  Stopping Debezium Server..."
        $debeziumProcesses | Stop-Process -Force
        Write-Host "  Debezium Server stopped"
    } else {
        Write-Host "  Debezium Server not running, skipping..." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Failed to stop Debezium Server, skipping..." -ForegroundColor Yellow
}

Write-Host "=== Services Stop Complete ===" -ForegroundColor Green
Write-Host "Please stop the back-end and front-end services manually if they are running."
