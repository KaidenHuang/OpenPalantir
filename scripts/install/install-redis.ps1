<#
.SYNOPSIS
Installs Redis from local package

.DESCRIPTION
This script installs Redis from local package and configures it as a service
#>

# Set error handling
$ErrorActionPreference = "Stop"

# Define variables
$currentDir = Get-Location
$dependenciesDir = "$currentDir\dependencies"
$localRedisDir = "$dependenciesDir\redis\local"
$extractDir = "$dependenciesDir\redis\extracted"

Write-Host "=== Installing Redis ===" -ForegroundColor Green

# Create necessary directories
New-Item -ItemType Directory -Path $dependenciesDir -Force | Out-Null
New-Item -ItemType Directory -Path "$dependenciesDir\redis" -Force | Out-Null

if (Test-Path $localRedisDir) {
    Write-Host "  Found local Redis package, using offline installation..."
    
    # Check if there's a zip file to extract
    $redisZip = Get-ChildItem -Path $localRedisDir -Name "*.zip" | Select-Object -First 1
    if ($redisZip) {
        Write-Host "  Found Redis zip file, extracting..."
        New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
        Expand-Archive -Path "$localRedisDir\$redisZip" -DestinationPath $extractDir -Force
        
        # Check if the zip contained a single directory
        $extractedItems = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
        if ($extractedItems) {
            # Move contents from subdirectory to extracted directory
            $subDir = $extractedItems.FullName
            Get-ChildItem -Path $subDir | Move-Item -Destination $extractDir -Force
            Remove-Item -Path $subDir -Recurse -Force
        }
        
        $localRedisDir = $extractDir
    }
    
    $redisServerExe = Get-ChildItem -Path $localRedisDir -Recurse -Name "redis-server.exe" | Select-Object -First 1
    if ($redisServerExe) {
        # Use local Redis directory directly
        $redisServerPath = "$localRedisDir\$redisServerExe"
        
        # Configure Redis
        Write-Host "  Configuring Redis..."
        $redisConf = Get-ChildItem -Path $localRedisDir -Recurse -Name "redis.windows.conf" | Select-Object -First 1
        if ($redisConf) {
            $redisConfPath = "$localRedisDir\$redisConf"
            # Backup original config
            Copy-Item -Path $redisConfPath -Destination "$redisConfPath.bak" -Force
            # Update config
            (Get-Content $redisConfPath) -replace "bind 127.0.0.1", "bind 127.0.0.1" | Set-Content $redisConfPath
            (Get-Content $redisConfPath) -replace "protected-mode yes", "protected-mode no" | Set-Content $redisConfPath
            (Get-Content $redisConfPath) -replace "port 6379", "port 6379" | Set-Content $redisConfPath
            (Get-Content $redisConfPath) -replace "dir .\/", "dir $localRedisDir\" | Set-Content $redisConfPath

            # Install Redis service
            Write-Host "  Installing Redis service..."
            & "$redisServerPath" --service-install "$redisConfPath" --loglevel verbose
            & "$redisServerPath" --service-start

            # Wait for Redis to start
            Start-Sleep -Seconds 3
            
            # Test Redis connection
            $redisCliExe = Get-ChildItem -Path $localRedisDir -Recurse -Name "redis-cli.exe" | Select-Object -First 1
            if ($redisCliExe) {
                $redisCliPath = "$localRedisDir\$redisCliExe"
                Write-Host "  Testing Redis connection..."
                $result = & "$redisCliPath" ping
                if ($result -eq "PONG") {
                    Write-Host "  Redis installation successful!" -ForegroundColor Green
                    return $true
                } else {
                    Write-Host "  Redis connection test failed" -ForegroundColor Red
                    return $false
                }
            }
        } else {
            Write-Host "  redis.windows.conf not found, skipping Redis configuration..." -ForegroundColor Yellow
            return $false
        }
    } else {
        Write-Host "  Local Redis package is invalid, skipping Redis installation..." -ForegroundColor Yellow
        return $false
    }
} else {
    Write-Host "  Local Redis package not found, skipping Redis installation..." -ForegroundColor Yellow
    return $false
}
