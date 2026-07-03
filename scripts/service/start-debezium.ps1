<#
.SYNOPSIS
启动指定实例的 Debezium Server（不影响 Neo4j / Redis）

.DESCRIPTION
参数 -InstanceId = connection_id。启动 instances/{InstanceId}/run.bat，
PID 写入 instances/{InstanceId}/debezium.pid 供精确停止。
供 cdc_manager.configure_connection() 调用。
#>
param([Parameter(Mandatory=$true)][String]$InstanceId)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Continue"

$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$instanceDir = "$projectRoot\dependencies\debezium\instances\$InstanceId"
$runBat = "$instanceDir\run.bat"

Write-Host "=== Starting Debezium instance $InstanceId ===" -ForegroundColor Green

if (-not (Test-Path $runBat)) {
    Write-Host "  实例目录未就绪（run.bat 不存在）: $instanceDir" -ForegroundColor Red
    exit 1
}

$dataDir = "$instanceDir\data\debezium"
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$logFile = "$dataDir\debezium.log"
$errFile = "$dataDir\debezium-error.log"

$p = Start-Process -FilePath $runBat -WorkingDirectory $instanceDir `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile `
    -WindowStyle Hidden -PassThru
Set-Content -Path "$instanceDir\debezium.pid" -Value $p.Id -Encoding ascii
Write-Host "  实例 $InstanceId Debezium 已启动 (pid=$($p.Id))" -ForegroundColor Green
Write-Host "  日志: $logFile" -ForegroundColor Green
