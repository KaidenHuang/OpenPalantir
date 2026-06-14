<#
.SYNOPSIS
Installs front-end dependencies and starts front-end service

.DESCRIPTION
This script installs front-end dependencies, builds the front-end application, and optionally starts the front-end service
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
$frontendDir = "$projectRoot\frontend"

Initialize-LogFile -Action "install-frontend" -LogFilePath $LogFilePath

if (Test-Path $frontendDir) {
    Set-Location $frontendDir

    # Log offline/online installation mode
    $localFrontendDir = "$dependenciesDir\frontend\local"
    if (Test-Path $localFrontendDir) {
        if (Test-Path "$localFrontendDir\package.json") {
            Write-Log "Using offline installation from local packages"
        } else {
            Write-Log "Local package.json not found, using online installation"
        }
    } else {
        Write-Log "No local packages found, using online installation"
    }

    # Clean up stale local npm from node_modules (can cause "Cannot find module" errors)
    $localNpmDir = "$frontendDir\node_modules\npm"
    if (Test-Path $localNpmDir) {
        Write-Host "  Removing stale local npm from node_modules..."
        Write-Log "Removing stale local npm at $localNpmDir"
        Remove-Item -Path $localNpmDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    # Determine npm CLI path to avoid npm.cmd prefix resolution issues
    # npm.cmd uses a prefix lookup that can fail if npm prefix points to a broken local install
    $npmCliJs = $null
    $nodeExePath = $null
    $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if ($npmCmd) {
        $nodeJsDir = Split-Path $npmCmd -Parent
        $npmCliCandidate = Join-Path $nodeJsDir "node_modules\npm\bin\npm-cli.js"
        if (Test-Path $npmCliCandidate) {
            $npmCliJs = $npmCliCandidate
            $nodeExePath = Join-Path $nodeJsDir "node.exe"
            Write-Log "Resolved npm-cli.js: $npmCliJs"
        }
    }

    # Remove any self-referential global symlink left by a previous --global install.
    # `npm install --global` with no package args, run inside a project dir, links the project
    # itself into the global node_modules (e.g. analysis-decision-system-frontend -> frontend/).
    # Once present, later global installs report "up to date" and fetch nothing, leaving the
    # project without its dependencies. Purge it so installs are never short-circuited.
    Write-Host "  Cleaning up stale global self-link if present..."
    if ($npmCliJs -and (Test-Path $nodeExePath)) {
        Invoke-LoggedProcess -FilePath $nodeExePath -ArgumentList @($npmCliJs, "uninstall", "--global", "analysis-decision-system-frontend") -WorkingDirectory $frontendDir | Out-Null
    } else {
        Invoke-LoggedProcess -FilePath "npm" -ArgumentList @("uninstall", "--global", "analysis-decision-system-frontend") -WorkingDirectory $frontendDir -UseCmdShell | Out-Null
    }

    # If frontend/node_modules is a leftover junction/symlink to a global dir (a remnant of the
    # old global-install strategy), remove the LINK ONLY via rmdir so npm can create a real
    # local node_modules. Remove-Item -Recurse on a junction would delete the TARGET's contents.
    # Real directories (a previous local install) are left in place for npm to update.
    $localNodeModules = "$frontendDir\node_modules"
    if (Test-Path $localNodeModules) {
        $linkType = (Get-Item $localNodeModules -Force).LinkType
        if ($linkType) {
            Write-Host "  Removing stale node_modules link from previous global install..."
            Write-Log "Removing link at $localNodeModules (LinkType=$linkType)"
            cmd /c rmdir "$localNodeModules" | Out-Null
        }
    }

    # Install dependencies into a LOCAL node_modules. This is required for `npm run build`:
    # npm resolves script binaries (tsc, vite, eslint) from node_modules/.bin, which only a
    # local install creates. A --global install drops bin shims in the npm prefix dir instead
    # and never populates node_modules/.bin, so `tsc && vite build` cannot find tsc/vite.
    Write-Host "  Installing front-end dependencies..."
    if ($npmCliJs -and (Test-Path $nodeExePath)) {
        # Direct invocation bypasses npm.cmd prefix lookup and cmd.exe quoting issues.
        $exitCode = Invoke-LoggedProcess -FilePath $nodeExePath -ArgumentList @($npmCliJs, "install", "--legacy-peer-deps") -WorkingDirectory $frontendDir
    } else {
        $exitCode = Invoke-LoggedProcess -FilePath "npm" -ArgumentList @("install", "--legacy-peer-deps") -WorkingDirectory $frontendDir -UseCmdShell
    }
    if ($exitCode -ne 0) {
        Write-Log "npm install failed with exit code $exitCode" -Level ERROR
        Write-Host "  npm install failed, check log: $script:LogFilePath" -ForegroundColor Red
        Set-Location $currentDir
        return $false
    }

    # Build front-end. Two constraints must hold simultaneously:
    #  1. Avoid npm.cmd's prefix lookup: npm.cmd resolves its own CLI from the CWD's
    #     node_modules\npm\bin\npm-cli.js and fails ("Cannot find module ... npm-prefix.js")
    #     when that path is absent. Invoking node.exe with the real npm-cli.js (resolved above)
    #     sidesteps npm.cmd entirely.
    #  2. Use the cmd-shell redirect (cmd /c "node npm-cli.js run build >> log 2>&1") instead of
    #     Invoke-LoggedProcess's Start-Process redirect: `npm run build` spawns tsc.cmd/vite.cmd
    #     and emits a lot of output, which Start-Process -RedirectStandardOutput mishandles,
    #     returning exit code -1 even on a successful build.
    Write-Host "  Building front-end..."
    if ($npmCliJs -and (Test-Path $nodeExePath)) {
        $exitCode = Invoke-LoggedProcess -FilePath $nodeExePath -ArgumentList @($npmCliJs, "run", "build") -WorkingDirectory $frontendDir -UseCmdShell
    } else {
        $exitCode = Invoke-LoggedProcess -FilePath "npm" -ArgumentList @("run", "build") -WorkingDirectory $frontendDir -UseCmdShell
    }
    if ($exitCode -ne 0) {
        Write-Log "npm run build failed with exit code $exitCode" -Level ERROR
        Write-Host "  npm run build failed, check log: $script:LogFilePath" -ForegroundColor Red
        Set-Location $currentDir
        return $false
    }

    # Start front-end service if requested
    if ($StartService) {
        Write-Host "  Starting front-end service..." -ForegroundColor Cyan
        Write-Host "  Front-end service will run on http://127.0.0.1:5173"
        Write-Host "  To start the service, navigate to frontend directory and run: npm run dev"
        Write-Host "  Press Ctrl+C to stop the service"
        Write-Host "  Starting service now..."
        Write-Log "Starting front-end service (npm run dev)"
        npm run dev
    }

    Set-Location $currentDir
    Write-Log "Front-end installation successful"
    Write-Host "  Front-end installation successful!" -ForegroundColor Green
    return $true
} else {
    Write-Log "Front-end directory not found, skipping" -Level WARN
    Write-Host "  Front-end directory not found, skipping front-end dependency installation" -ForegroundColor Yellow
    return $false
}
