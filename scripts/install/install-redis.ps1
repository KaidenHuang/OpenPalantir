<#
.SYNOPSIS
Installs Redis from local package

.DESCRIPTION
This script installs Redis from local package and configures it as a service
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
$localRedisDir = "$dependenciesDir\redis\local"
$extractDir = "$dependenciesDir\redis\extracted"

Initialize-LogFile -Action "install-redis" -LogFilePath $LogFilePath

Write-Host "=== Installing Redis ===" -ForegroundColor Green
Write-Log "Installing Redis"

# Create necessary directories
New-Item -ItemType Directory -Path $dependenciesDir -Force | Out-Null
New-Item -ItemType Directory -Path "$dependenciesDir\redis" -Force | Out-Null

if (Test-Path $localRedisDir) {
    Write-Host "  Found local Redis package, using offline installation..."
    Write-Log "Using local Redis package from $localRedisDir"

    # Check if there's a zip file to extract
    $redisZip = Get-ChildItem -Path $localRedisDir -Name "*.zip" | Select-Object -First 1
    if ($redisZip) {
        Write-Host "  Found Redis zip file, extracting..."
        Write-Log "Extracting $redisZip to $extractDir"
        New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
        try {
            Expand-Archive -Path "$localRedisDir\$redisZip" -DestinationPath $extractDir -Force
            Write-Log "Extracted $redisZip successfully"
        } catch {
            Write-Log "Expand-Archive failed: $($_.Exception.Message)" -Level ERROR
        }

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
        Write-Log "Using redis-server at $redisServerPath"

        # Configure Redis
        Write-Host "  Configuring Redis..."
        Write-Log "Configuring Redis"
        # Use redis.windows-service.conf for service installation (redis.windows.conf is for foreground mode)
        $redisConf = Get-ChildItem -Path $localRedisDir -Recurse -Name "redis.windows-service.conf" -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $redisConf) {
            $redisConf = Get-ChildItem -Path $localRedisDir -Recurse -Name "redis.windows.conf" -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if ($redisConf) {
            $redisConfPath = "$localRedisDir\$redisConf"
            # Backup original config
            Copy-Item -Path $redisConfPath -Destination "$redisConfPath.bak" -Force
            # Read once, modify in memory, write once (avoids file corruption from repeated Get-Content|Set-Content)
            $configContent = Get-Content $redisConfPath -Raw
            $configContent = $configContent -replace "protected-mode yes", "protected-mode no"
            $redisDataDir = ($localRedisDir -replace '\\', '/')
            $configContent = [regex]::Replace($configContent, '(?m)^dir\s+\./', "dir $redisDataDir")
            Set-Content -Path $redisConfPath -Value $configContent -NoNewline
            Write-Log "Redis config updated: $redisConfPath"

            # Install Redis service
            Write-Host "  Installing Redis service..."
            Write-Log "Installing Redis service with config: $redisConfPath"
            $exitCode = Invoke-LoggedProcess -FilePath $redisServerPath -ArgumentList @("--service-install", $redisConfPath, "--loglevel", "verbose") -UseCmdShell
            if ($exitCode -ne 0) {
                Write-Log "redis-server --service-install failed (exit code $exitCode)" -Level ERROR
                Write-Host "  Redis service install failed, check log: $script:LogFilePath" -ForegroundColor Red
                return $false
            }
            $exitCode = Invoke-LoggedProcess -FilePath $redisServerPath -ArgumentList @("--service-start") -UseCmdShell
            if ($exitCode -ne 0) {
                Write-Log "redis-server --service-start failed (exit code $exitCode)" -Level ERROR
            }

            # Wait for Redis to start
            Start-Sleep -Seconds 3

            # Test Redis connection
            $redisCliExe = Get-ChildItem -Path $localRedisDir -Recurse -Name "redis-cli.exe" | Select-Object -First 1
            if ($redisCliExe) {
                $redisCliPath = "$localRedisDir\$redisCliExe"
                Write-Host "  Testing Redis connection..."
                $result = & "$redisCliPath" ping
                Write-Log "redis-cli ping result: $result"
                if ($result -eq "PONG") {
                    Write-Host "  Redis installation successful!" -ForegroundColor Green
                    Write-Log "Redis installation successful"
                    return $true
                } else {
                    Write-Host "  Redis connection test failed" -ForegroundColor Red
                    Write-Log "Redis connection test failed: expected PONG, got $result" -Level ERROR
                    return $false
                }
            }
        } else {
            Write-Host "  redis.windows.conf not found, skipping Redis configuration..." -ForegroundColor Yellow
            Write-Log "redis.windows.conf not found" -Level ERROR
            return $false
        }
    } else {
        Write-Host "  Local Redis package is invalid, skipping Redis installation..." -ForegroundColor Yellow
        Write-Log "redis-server.exe not found in $localRedisDir" -Level ERROR
        return $false
    }
} else {
    Write-Host "  Local Redis package not found, skipping Redis installation..." -ForegroundColor Yellow
    Write-Log "Local Redis package not found at $localRedisDir" -Level WARN
    return $false
}
