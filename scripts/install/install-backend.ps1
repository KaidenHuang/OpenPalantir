<#
.SYNOPSIS
Installs back-end dependencies and starts back-end service

.DESCRIPTION
This script installs back-end dependencies and optionally starts the back-end service
#>

# Define parameters
param(
    [switch]$StartService = $false
)

# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$dependenciesDir = "$currentDir\dependencies"
$backendDir = "$currentDir\backend"
$envFile = "$backendDir\.env"

Write-Host "=== Installing Back-end Dependencies ===" -ForegroundColor Green

if (Test-Path $backendDir) {
    Set-Location $backendDir
    $localBackendDir = "$dependenciesDir\backend\local"
    if (Test-Path $localBackendDir) {
        Write-Host "  Found local back-end dependencies, using offline installation..."
        if (Test-Path "$localBackendDir\requirements.txt") {
            Write-Host "  Installing back-end dependencies from local package..."
            $process = Start-Process -FilePath "pip" -ArgumentList "install", "--no-index", "--find-links=$localBackendDir", "-r", "requirements.txt" -Wait -NoNewWindow -PassThru -RedirectStandardOutput "pip_output.txt" -RedirectStandardError "pip_error.txt"
        } else {
            Write-Host "  Local back-end dependencies not found, trying online installation..." -ForegroundColor Yellow
            Write-Host "  Running pip install with国内镜像源..."
            $process = Start-Process -FilePath "pip" -ArgumentList "install", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "-r", "requirements.txt" -Wait -NoNewWindow -PassThru -RedirectStandardOutput "pip_output.txt" -RedirectStandardError "pip_error.txt"
        }
    } else {
        Write-Host "  Running pip install with国内镜像源..."
        $process = Start-Process -FilePath "pip" -ArgumentList "install", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "-r", "requirements.txt" -Wait -NoNewWindow -PassThru -RedirectStandardOutput "pip_output.txt" -RedirectStandardError "pip_error.txt"
    }
    
    # Display output
    if (Test-Path "pip_output.txt") {
        Write-Host (Get-Content "pip_output.txt")
        Remove-Item "pip_output.txt"
    }
    if (Test-Path "pip_error.txt") {
        Write-Host (Get-Content "pip_error.txt")
        Remove-Item "pip_error.txt"
    }
    
    if ($process.ExitCode -ne 0) {
        Write-Host "  pip install failed with exit code $($process.ExitCode)" -ForegroundColor Red
        Set-Location $currentDir
        return $false
    }
    
    # Create environment variables file
    Write-Host "  Creating environment variables file..."
    $envContent = @'
# Neo4j configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here

# Redis configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Celery configuration
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

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
        $fallbackEnvFile = "$currentDir\.env"
        Set-Content -Path $fallbackEnvFile -Value $envContent
        Write-Host "  Created environment variables file at $fallbackEnvFile" -ForegroundColor Yellow
    }
    
    # Start back-end service if requested
    if ($StartService) {
        Write-Host "  Starting back-end service..." -ForegroundColor Cyan
        Write-Host "  Back-end service will run on http://localhost:8000"
        Write-Host "  API documentation available at http://localhost:8000/docs"
        Write-Host "  To start the service, navigate to backend directory and run: python -m uvicorn main:app --reload"
        Write-Host "  Press Ctrl+C to stop the service"
        Write-Host "  Starting service now..."
        python -m uvicorn main:app --reload
    }
    
    Set-Location $currentDir
    Write-Host "  Back-end installation successful!" -ForegroundColor Green
    return $true
} else {
    Write-Host "  Back-end directory not found, skipping back-end dependency installation" -ForegroundColor Yellow
    return $false
}
