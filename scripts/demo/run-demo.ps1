<#
.SYNOPSIS
Runs the OpenPalantir Wiki + ontology one-click demo

.DESCRIPTION
Thin wrapper around scripts/demo/run_demo.py. Requires the backend on
http://localhost:8000 (see scripts/service/start-services.ps1 for Neo4j/Redis).
Pass-through arguments: -Domain rd_efficiency -NoPack -Timeout 1200
#>
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Script = Join-Path $RepoRoot "scripts\demo\run_demo.py"

$Python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
& $Python $Script @args
exit $LASTEXITCODE
