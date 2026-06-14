<#
.SYNOPSIS
Uninstalls Redis service and cleans up extracted files

.DESCRIPTION
This script stops and uninstalls Redis service and removes extracted files
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
$redisDir = "$dependenciesDir\redis"
$extractDir = "$redisDir\extracted"

Initialize-LogFile -Action "uninstall-redis" -LogFilePath $LogFilePath

Write-Host "=== Uninstalling Redis ===" -ForegroundColor Green
Write-Log "Uninstalling Redis"

# Stop Redis service
Write-Host "  Stopping Redis service..."
Write-Log "Stopping Redis service"
try {
    $redisServerExe = Get-ChildItem -Path $extractDir -Recurse -Name "redis-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($redisServerExe) {
        $redisServerPath = "$extractDir\$redisServerExe"
        # Best-effort: redis-server --service-stop / --service-uninstall may return
        # non-zero silently (service not under the default name, already removed, or
        # started as a plain process). We log the exit codes but do not abort here;
        # the process kill below is the reliable fallback.
        Write-Log "Running redis-server.exe --service-stop"
        $stopCode = Invoke-LoggedProcess -FilePath $redisServerPath -ArgumentList @("--service-stop") -UseCmdShell
        Write-Log "redis-server.exe --service-stop exit code: $stopCode"
        Write-Log "Running redis-server.exe --service-uninstall"
        $uninstallCode = Invoke-LoggedProcess -FilePath $redisServerPath -ArgumentList @("--service-uninstall") -UseCmdShell
        Write-Log "redis-server.exe --service-uninstall exit code: $uninstallCode"
    } else {
        Write-Host "  Redis server executable not found, skipping service CLI" -ForegroundColor Yellow
        Write-Log "redis-server.exe not found in $extractDir, skipping service CLI" -Level WARN
    }

    # Fallback 1: if the CLI left a "Redis" service registration behind, remove it
    # via sc.exe (PS "sc" is an alias for Set-Content, must call sc.exe explicitly).
    $redisSvc = Get-Service -Name "Redis" -ErrorAction SilentlyContinue
    if ($redisSvc) {
        Write-Log "Redis service still registered (State=$($redisSvc.Status)), removing via sc.exe"
        if ($redisSvc.Status -ne 'Stopped') {
            try { Stop-Service -Name $redisSvc.Name -Force -ErrorAction SilentlyContinue } catch {}
            Start-Sleep -Milliseconds 500
        }
        & sc.exe delete $redisSvc.Name 2>&1 | ForEach-Object { Write-Log "sc.exe delete: $_" }
    }

    # Fallback 2: kill any running redis-server process. This is the real fix for
    # "access denied on redis-server.exe" -- the service CLI can report success while
    # a process (service worker or a manually started instance) still locks the exe.
    $procs = Get-Process -Name "redis-server" -ErrorAction SilentlyContinue
    if ($procs) {
        Write-Host "  Found $($procs.Count) running redis-server process(es), terminating..." -ForegroundColor Yellow
        Write-Log "Terminating redis-server PID(s): $($procs.Id -join ', ')"
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        # Let the OS release the file handles before we delete the directory
        Start-Sleep -Seconds 1
    }

    Write-Host "  Redis stopped" -ForegroundColor Green
    Write-Log "Redis stop sequence complete"
} catch {
    Write-Host "  Failed to stop Redis service: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Log "Failed to stop Redis service: $($_.Exception.Message)" -Level ERROR
}

# Clean up extracted directory
Write-Host "  Cleaning up Redis extracted directory..."
Write-Log "Cleaning up Redis extracted directory: $extractDir"
try {
    if (Test-Path $extractDir) {
        Remove-Item -Path $extractDir -Recurse -Force -ErrorAction Stop
        Write-Host "  Redis extracted directory cleaned up successfully" -ForegroundColor Green
        Write-Log "Removed $extractDir"
    } else {
        Write-Host "  Redis extracted directory not found, skipping cleanup" -ForegroundColor Yellow
        Write-Log "Redis extracted directory not found, skipping"
    }
    return $true
} catch {
    Write-Host "  Failed to clean up Redis extracted directory: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  A redis-server.exe process may still be locking the file." -ForegroundColor Yellow
    Write-Host "  Run these in an elevated PowerShell, then re-run uninstall:" -ForegroundColor Yellow
    Write-Host "    Stop-Process -Name redis-server -Force" -ForegroundColor Cyan
    Write-Host "    Remove-Item -Recurse -Force `"$extractDir`"" -ForegroundColor Cyan
    Write-Log "Failed to remove ${extractDir}: $($_.Exception.Message)" -Level ERROR
    return $false
}
