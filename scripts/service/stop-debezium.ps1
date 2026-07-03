<#
.SYNOPSIS
停止指定实例的 Debezium Server（不影响 Neo4j / Redis）

.DESCRIPTION
参数 -InstanceId = connection_id。读 instances/{InstanceId}/debezium.pid 停止对应进程。
#>
param([Parameter(Mandatory=$true)][String]$InstanceId)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Continue"

$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$instanceDir = "$projectRoot\dependencies\debezium\instances\$InstanceId"
$pidFile = "$instanceDir\debezium.pid"

Write-Host "=== Stopping Debezium instance $InstanceId ===" -ForegroundColor Green

if (-not (Test-Path $pidFile)) {
    Write-Host "  实例 $InstanceId 无 pid 文件（未运行或非 start-debezium 启动）" -ForegroundColor Yellow
    exit 0
}

$procId = (Get-Content $pidFile | Select-Object -First 1).Trim()
try {
    Stop-Process -Id $procId -Force -ErrorAction Stop
    Write-Host "  实例 $InstanceId Debezium 已停止 (pid=$procId)" -ForegroundColor Green
} catch {
    Write-Host "  进程 $procId 不存在或已退出" -ForegroundColor Yellow
}
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
