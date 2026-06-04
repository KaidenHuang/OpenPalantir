<#
.SYNOPSIS
Uninstalls Neo4j

.DESCRIPTION
This script uninstalls Neo4j by stopping the service, uninstalling it, and removing the installation directory
#>

# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$dependenciesDir = "$currentDir\dependencies"
$neo4jDir = "$dependenciesDir\neo4j"
$extractDir = "$neo4jDir\extracted"
$neo4jHome = "$extractDir\neo4j-community-4.4.8"
$neo4jBin = "$neo4jHome\bin\neo4j.bat"

function Uninstall-Neo4jService {
    Write-Host "=== Uninstalling Neo4j Service ===" -ForegroundColor Green
    
    if (-not (Test-Path $neo4jBin)) {
        Write-Host "Neo4j executable not found" -ForegroundColor Red
        return $false
    }
    
    # Stop service first
    Set-Location (Split-Path $neo4jBin -Parent)
    & .\neo4j.bat stop
    Start-Sleep -Seconds 2
    
    # Uninstall service
    & .\neo4j.bat uninstall-service
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Neo4j service uninstalled successfully" -ForegroundColor Green
        Set-Location $currentDir
        return $true
    } else {
        Write-Host "Neo4j service uninstallation failed" -ForegroundColor Red
        Set-Location $currentDir
        return $false
    }
}

function Remove-Neo4jDirectory {
    Write-Host "=== Removing Neo4j Directory ===" -ForegroundColor Green
    
    if (Test-Path $extractDir) {
        Remove-Item -Path $extractDir -Recurse -Force
        Write-Host "Neo4j extracted directory removed" -ForegroundColor Green
        return $true
    } else {
        Write-Host "Neo4j extracted directory not found" -ForegroundColor Yellow
        return $true
    }
}

# Main uninstall process
Uninstall-Neo4jService
Remove-Neo4jDirectory
Write-Host "Neo4j uninstallation completed" -ForegroundColor Green
