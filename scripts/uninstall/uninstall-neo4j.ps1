<#
.SYNOPSIS
Uninstalls Neo4j

.DESCRIPTION
This script uninstalls Neo4j by stopping the service, uninstalling it, and removing the installation directory
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
$neo4jDir = "$dependenciesDir\neo4j"
$extractDir = "$neo4jDir\extracted"

# Auto-detect Neo4j version directory (works for both 4.x and 5.x)
$neo4jHomeDir = Get-ChildItem -Path $extractDir -Directory -Filter "neo4j-community-*" -ErrorAction SilentlyContinue | Select-Object -First 1
$neo4jHome = if ($neo4jHomeDir) { $neo4jHomeDir.FullName } else { "$extractDir\neo4j-community-5.26.27" }
$neo4jBin = "$neo4jHome\bin\neo4j.bat"

Initialize-LogFile -Action "uninstall-neo4j" -LogFilePath $LogFilePath

function Uninstall-Neo4jService {
    Write-Host "=== Uninstalling Neo4j Service ===" -ForegroundColor Green
    Write-Log "Uninstalling Neo4j service"

    # Stop service first using Windows service management
    $svc = Get-Service -Name "Neo4j" -ErrorAction SilentlyContinue
    if (-not $svc) {
        $svc = Get-Service | Where-Object { $_.DisplayName -eq 'Neo4j' }
    }
    if ($svc -and $svc.Status -eq 'Running') {
        Write-Host "  Stopping Neo4j service..."
        Write-Log "Issuing net stop $($svc.Name) via wscript UAC elevation"
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
    }

    # Uninstall service using neo4j.bat (Neo4j 5.x: "windows-service uninstall", 4.x: "uninstall-service")
    if (Test-Path $neo4jBin) {
        $neo4jBinDir = Split-Path $neo4jBin -Parent
        Set-Location $neo4jBinDir
        Write-Log "Running neo4j.bat windows-service uninstall"
        $exitCode = Invoke-LoggedProcess -FilePath ".\neo4j.bat" -ArgumentList @("windows-service", "uninstall") -WorkingDirectory $neo4jBinDir -UseCmdShell

        if ($exitCode -ne 0) {
            Write-Host "Retrying with legacy uninstall-service command..."
            Write-Log "Retrying with neo4j.bat uninstall-service"
            $exitCode = Invoke-LoggedProcess -FilePath ".\neo4j.bat" -ArgumentList @("uninstall-service") -WorkingDirectory $neo4jBinDir -UseCmdShell
        }
        Set-Location $currentDir
    }

    # Verify removal
    $svc = Get-Service -Name "Neo4j" -ErrorAction SilentlyContinue
    if (-not $svc) {
        $svc = Get-Service | Where-Object { $_.DisplayName -eq 'Neo4j' }
    }
    if (-not $svc) {
        Write-Host "Neo4j service uninstalled successfully" -ForegroundColor Green
        Write-Log "Neo4j service uninstalled successfully"
        return $true
    } else {
        Write-Host "Neo4j service still exists after uninstall attempt" -ForegroundColor Yellow
        Write-Log "Neo4j service still exists after uninstall attempt" -Level WARN
        return $false
    }
}

function Remove-Neo4jDirectory {
    Write-Host "=== Removing Neo4j Directory ===" -ForegroundColor Green
    Write-Log "Removing Neo4j directory: $extractDir"

    if (Test-Path $extractDir) {
        try {
            Remove-Item -Path $extractDir -Recurse -Force
            Write-Host "Neo4j extracted directory removed" -ForegroundColor Green
            Write-Log "Removed $extractDir"
            return $true
        } catch {
            Write-Host "Failed to remove Neo4j directory: $($_.Exception.Message)" -ForegroundColor Red
            Write-Log "Failed to remove ${extractDir}: $($_.Exception.Message)" -Level ERROR
            return $false
        }
    } else {
        Write-Host "Neo4j extracted directory not found" -ForegroundColor Yellow
        Write-Log "Neo4j extracted directory not found, skipping"
        return $true
    }
}

# Main uninstall process
Uninstall-Neo4jService
Remove-Neo4jDirectory
Write-Host "Neo4j uninstallation completed" -ForegroundColor Green
Write-Log "Neo4j uninstallation completed"
return $true
