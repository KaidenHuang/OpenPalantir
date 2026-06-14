<#
.SYNOPSIS
Uninstalls Debezium Server and cleans up extracted files

.DESCRIPTION
This script stops Debezium Server processes, removes extracted files,
and cleans up the Debezium data directory
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
$dependenciesDir = "$projectRoot\dependencies"
$debeziumDir = "$dependenciesDir\debezium"
$extractDir = "$debeziumDir\extracted"

Initialize-LogFile -Action "uninstall-debezium" -LogFilePath $LogFilePath

function Stop-DebeziumProcesses {
    Write-Host "=== Stopping Debezium Processes ===" -ForegroundColor Green
    Write-Log "Stopping Debezium processes"

    try {
        $debeziumProcesses = Get-Process -Name "java" -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -match "debezium-server" -or $_.CommandLine -match "io\.debezium\.server"
        }
        if ($debeziumProcesses) {
            Write-Host "  Stopping Debezium Server processes..."
            foreach ($proc in $debeziumProcesses) {
                Write-Log "Stopping Debezium process PID $($proc.Id)"
            }
            $debeziumProcesses | Stop-Process -Force
            Start-Sleep -Seconds 2
            Write-Host "  Debezium processes stopped" -ForegroundColor Green
            Write-Log "Debezium processes stopped"
        } else {
            Write-Host "  No Debezium processes running" -ForegroundColor Yellow
            Write-Log "No Debezium processes running"
        }
    } catch {
        Write-Host "  Failed to stop Debezium processes: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Log "Failed to stop Debezium processes: $($_.Exception.Message)" -Level ERROR
    }

    return $true
}

function Remove-DebeziumExtractedDirectory {
    Write-Host "=== Removing Debezium Extracted Directory ===" -ForegroundColor Green
    Write-Log "Removing Debezium extracted directory: $extractDir"

    if (Test-Path $extractDir) {
        try {
            Remove-Item -Path $extractDir -Recurse -Force
            Write-Host "  Debezium extracted directory removed" -ForegroundColor Green
            Write-Log "Removed $extractDir"
        } catch {
            Write-Host "  Failed to remove Debezium extracted directory: $($_.Exception.Message)" -ForegroundColor Red
            Write-Log "Failed to remove ${extractDir}: $($_.Exception.Message)" -Level ERROR
        }
    } else {
        Write-Host "  Debezium extracted directory not found, skipping" -ForegroundColor Yellow
        Write-Log "Debezium extracted directory not found, skipping"
    }

    return $true
}

function Remove-DebeziumDataDirectory {
    Write-Host "=== Removing Debezium Data Directory ===" -ForegroundColor Green
    $debeziumDataDir = "$projectRoot\backend\data\debezium"
    Write-Log "Removing Debezium data directory: $debeziumDataDir"

    if (Test-Path $debeziumDataDir) {
        try {
            Remove-Item -Path $debeziumDataDir -Recurse -Force
            Write-Host "  Debezium data directory removed" -ForegroundColor Green
            Write-Log "Removed $debeziumDataDir"
        } catch {
            Write-Host "  Failed to remove Debezium data directory: $($_.Exception.Message)" -ForegroundColor Red
            Write-Log "Failed to remove ${debeziumDataDir}: $($_.Exception.Message)" -Level ERROR
        }
    } else {
        Write-Host "  Debezium data directory not found, skipping" -ForegroundColor Yellow
        Write-Log "Debezium data directory not found, skipping"
    }

    return $true
}

# Main uninstall process
Stop-DebeziumProcesses | Out-Null
Remove-DebeziumExtractedDirectory | Out-Null
Remove-DebeziumDataDirectory | Out-Null
Write-Host "Debezium uninstallation completed" -ForegroundColor Green
Write-Log "Debezium uninstallation completed"

return $true
