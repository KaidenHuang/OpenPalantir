<#
.SYNOPSIS
Installs back-end dependencies and starts back-end service

.DESCRIPTION
This script installs back-end dependencies and optionally starts the back-end service
#>
# Define parameters
param(
    [switch]$StartService = $false,
    [string]$LogFilePath
)

# Set error handling
$ErrorActionPreference = "Stop"

# Force UTF-8 output encoding to prevent garbled text
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Load logging helpers
. "$PSScriptRoot\..\install-uninstall-helpers.ps1"

# Define variables
$currentDir = Get-Location
$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$dependenciesDir = "$projectRoot\dependencies"
$backendDir = "$projectRoot\backend"
$envFile = "$backendDir\.env"

Initialize-LogFile -Action "install-backend" -LogFilePath $LogFilePath

if (Test-Path $backendDir) {
    Set-Location $backendDir
    $localBackendDir = "$dependenciesDir\backend\local"
    if (Test-Path $localBackendDir) {
        if (Test-Path "$localBackendDir\requirements.txt") {
            Write-Log "Using offline installation from local packages"
            $exitCode = Invoke-LoggedProcess -FilePath "pip" -ArgumentList @("install", "--no-index", "--find-links=$localBackendDir", "-r", "requirements.txt") -WorkingDirectory $backendDir
        } else {
            Write-Log "Local requirements.txt not found, using online installation"
            $exitCode = Invoke-LoggedProcess -FilePath "pip" -ArgumentList @("install", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "-r", "requirements.txt") -WorkingDirectory $backendDir
        }
    } else {
        Write-Log "No local packages found, using online installation"
        $exitCode = Invoke-LoggedProcess -FilePath "pip" -ArgumentList @("install", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "-r", "requirements.txt") -WorkingDirectory $backendDir
    }

    if ($exitCode -ne 0) {
        Write-Log "pip install failed with exit code $exitCode" -Level ERROR
        Write-Host "  pip install failed (exit code $exitCode), check log for details:" -ForegroundColor Red
        Write-Host "  $script:LogFilePath" -ForegroundColor Red
        Set-Location $currentDir
        return $false
    }
    
    # Create environment variables file
    Write-Host "  Creating environment variables file..."
    Write-Log "Creating environment variables file at $envFile"

    # Backup existing .env if present to avoid losing user customizations
    if (Test-Path $envFile) {
        $backupEnvFile = "$envFile.bak"
        Copy-Item -Path $envFile -Destination $backupEnvFile -Force
        Write-Host "  Existing .env backed up to $backupEnvFile" -ForegroundColor Yellow
        Write-Log "Backed up existing .env to $backupEnvFile"
    }

    $envContent = @'
# Neo4j configuration
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=1234qwer

# Redis configuration
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0

# Celery configuration
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0

# Other configuration
APP_ENV=development
APP_VERSION=1.0.0
CORS_ORIGINS=*
BATCH_SIZE=100
CACHE_TTL=3600
'@
    
    if (Test-Path $backendDir) {
        Set-Content -Path $envFile -Value $envContent
    } else {
        Write-Host "  Back-end directory not found, skipping environment variables file creation..." -ForegroundColor Yellow
        # Create the file in the current directory instead
        $fallbackEnvFile = "$projectRoot\.env"
        Set-Content -Path $fallbackEnvFile -Value $envContent
        Write-Host "  Created environment variables file at $fallbackEnvFile" -ForegroundColor Yellow
    }
    
    # Start back-end service if requested
    if ($StartService) {
        Write-Host "  Starting back-end service..." -ForegroundColor Cyan
        Write-Host "  Back-end service will run on http://127.0.0.1:8000"
        Write-Host "  API documentation available at http://127.0.0.1:8000/docs"
        Write-Host "  To start the service, navigate to backend directory and run: python -m uvicorn main:app --reload"
        Write-Host "  Press Ctrl+C to stop the service"
        Write-Host "  Starting service now..."
        python -m uvicorn main:app --reload
    }
    
    Set-Location $currentDir
    Write-Log "Back-end installation successful"
    Write-Host "  Back-end installation successful!" -ForegroundColor Green
    return $true
} else {
    Write-Log "Back-end directory not found, skipping" -Level WARN
    Write-Host "  Back-end directory not found, skipping back-end dependency installation" -ForegroundColor Yellow
    return $false
}
