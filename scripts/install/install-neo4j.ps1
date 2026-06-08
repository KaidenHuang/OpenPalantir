<#
.SYNOPSIS
Installs Neo4j

.DESCRIPTION
This script installs Neo4j with separated functions for each step
#>
# Force UTF-8 output encoding to prevent garbled text
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8


# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$dependenciesDir = "$currentDir\dependencies"
$neo4jDir = "$dependenciesDir\neo4j"
$extractDir = "$neo4jDir\extracted"
$localDir = "$neo4jDir\local"
$neo4jHome = "$extractDir\neo4j-community-4.4.8"
$neo4jBin = "$neo4jHome\bin\neo4j.bat"

function Extract-Neo4j {
    Write-Host "=== Extracting Neo4j ===" -ForegroundColor Green
    
    # Create directories
    New-Item -ItemType Directory -Path $neo4jDir -Force | Out-Null
    New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
    
    # Find and extract Neo4j zip
    $neo4jZip = Get-ChildItem -Path $localDir -Name "*.zip" | Select-Object -First 1
    if (-not $neo4jZip) {
        Write-Host "Neo4j zip file not found" -ForegroundColor Red
        return $false
    }
    
    Write-Host "Extracting $neo4jZip..."
    Expand-Archive -Path "$localDir\$neo4jZip" -DestinationPath $extractDir -Force
    
    # Verify extraction
    if (Test-Path $neo4jHome) {
        Write-Host "Neo4j extracted successfully" -ForegroundColor Green
        return $true
    } else {
        Write-Host "Neo4j extraction failed" -ForegroundColor Red
        return $false
    }
}

function Configure-Neo4j {
    Write-Host "=== Configuring Neo4j ===" -ForegroundColor Green
    
    # Define Neo4j data directories
    $neo4jConfigFile = "$neo4jHome\conf\neo4j.conf"
    $neo4jDataDir = "$currentDir\backend\data\neo4j\data"
    $neo4jLogsDir = "$currentDir\backend\data\neo4j\logs"
    
    # Create necessary directories
    New-Item -ItemType Directory -Path "$currentDir\backend\data\neo4j" -Force | Out-Null
    New-Item -ItemType Directory -Path $neo4jDataDir -Force | Out-Null
    New-Item -ItemType Directory -Path $neo4jLogsDir -Force | Out-Null
    
    # Modify neo4j.conf file
    if (Test-Path $neo4jConfigFile) {
        Write-Host "Modifying neo4j.conf file..."
        
        # Read the config file
        $configContent = Get-Content -Path $neo4jConfigFile
        
        # Update data and logs directories
        $configContent = $configContent -replace "#dbms.directories.data=data", "dbms.directories.data=$($neo4jDataDir -replace '\\', '/')"
        $configContent = $configContent -replace "#dbms.directories.logs=logs", "dbms.directories.logs=$($neo4jLogsDir -replace '\\', '/')"
        $configContent = $configContent -replace "#dbms.directories.transaction.logs.root=data/transactions", "dbms.directories.transaction.logs.root=$($neo4jDataDir -replace '\\', '/')/transactions"
        
        # Write the updated config file
        Set-Content -Path $neo4jConfigFile -Value $configContent
        
        Write-Host "Neo4j configuration updated successfully" -ForegroundColor Green
        return $true
    } else {
        Write-Host "Neo4j config file not found" -ForegroundColor Red
        return $false
    }
}

function Install-Neo4jService {
    Write-Host "=== Installing Neo4j Service ===" -ForegroundColor Green
    
    if (-not (Test-Path $neo4jBin)) {
        Write-Host "Neo4j executable not found" -ForegroundColor Red
        return $false
    }
    
    # Install service
    Set-Location (Split-Path $neo4jBin -Parent)
    & .\neo4j.bat install-service
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Neo4j service installed successfully" -ForegroundColor Green
        Set-Location $currentDir
        return $true
    } else {
        Write-Host "Neo4j service installation failed" -ForegroundColor Red
        Set-Location $currentDir
        return $false
    }
}

function Initialize-Neo4j {
    Write-Host "=== Initializing Neo4j ===" -ForegroundColor Green
    
    # Set NEO4J_HOME
    [Environment]::SetEnvironmentVariable("NEO4J_HOME", $neo4jHome, "User")
    $env:NEO4J_HOME = $neo4jHome
    Write-Host "Set NEO4J_HOME to $neo4jHome"
    
    # Set initial password
    $neo4jAdmin = "$neo4jHome\bin\neo4j-admin.bat"
    if (Test-Path $neo4jAdmin) {
        $env:NEO4J_ACCEPT_LICENSE_AGREEMENT = "yes"
        # Use Start-Process to avoid RemoteException in PowerShell ISE
        $process = Start-Process -FilePath $neo4jAdmin -ArgumentList "set-initial-password", "1234qwer" -Wait -NoNewWindow -PassThru
        
        if ($process.ExitCode -eq 0) {
            Write-Host "Initial password set successfully" -ForegroundColor Green
            return $true
        }
    }
    
    Write-Host "Neo4j initialization failed" -ForegroundColor Red
    return $false
}

function Start-Neo4jService {
    Write-Host "=== Starting Neo4j Service ===" -ForegroundColor Green
    
    if (-not (Test-Path $neo4jBin)) {
        Write-Host "Neo4j executable not found" -ForegroundColor Red
        return $false
    }
    
    # Start service
    Set-Location (Split-Path $neo4jBin -Parent)
    & .\neo4j.bat start
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Neo4j service started" -ForegroundColor Green
        Set-Location $currentDir
        return $true
    } else {
        Write-Host "Neo4j service start failed" -ForegroundColor Red
        Set-Location $currentDir
        return $false
    }
}

function Check-Neo4jStatus {
    Write-Host "=== Checking Neo4j Status ===" -ForegroundColor Green
    
    if (-not (Test-Path $neo4jBin)) {
        Write-Host "Neo4j executable not found" -ForegroundColor Red
        return $false
    }
    
    # Check status
    Set-Location (Split-Path $neo4jBin -Parent)
    $status = & .\neo4j.bat status
    
    Write-Host "Neo4j status: $status"
    Set-Location $currentDir
    
    return $status -like "*running*"
}

# Main install process
$neo4jSuccess = $false
if (Extract-Neo4j) {
    if (Configure-Neo4j) {
        if (Install-Neo4jService) {
            if (Initialize-Neo4j) {
                if (Start-Neo4jService) {
                    Start-Sleep -Seconds 5
                    if (Check-Neo4jStatus) {
                        Write-Host "Neo4j installation completed successfully!" -ForegroundColor Green
                        $neo4jSuccess = $true
                    } else {
                        Write-Host "Neo4j installation completed but service not running" -ForegroundColor Yellow
                        $neo4jSuccess = $false
                    }
                }
            }
        }
    }
}

return $neo4jSuccess
