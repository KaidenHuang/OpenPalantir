<#
.SYNOPSIS
Installs Neo4j

.DESCRIPTION
This script installs Neo4j with separated functions for each step
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
$neo4jDir = "$dependenciesDir\neo4j"
$extractDir = "$neo4jDir\extracted"
$localDir = "$neo4jDir\local"

# Auto-detect Neo4j version directory (works for both 4.x and 5.x)
$neo4jHomeDir = Get-ChildItem -Path $extractDir -Directory -Filter "neo4j-community-*" -ErrorAction SilentlyContinue | Select-Object -First 1
$neo4jHome = if ($neo4jHomeDir) { $neo4jHomeDir.FullName } else { "$extractDir\neo4j-community-5.26.27" }
$neo4jBin = "$neo4jHome\bin\neo4j.bat"

Initialize-LogFile -Action "install-neo4j" -LogFilePath $LogFilePath

function Check-JavaVersion {
    Write-Host "=== Checking Java Version ===" -ForegroundColor Green
    Write-Log "Checking Java version"
    try {
        # java -version writes to stderr, so we need Continue to avoid terminating error
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $javaVersionOutput = & java -version 2>&1
        $ErrorActionPreference = $prevEAP

        $versionLine = $javaVersionOutput | Select-Object -First 1
        Write-Host "  Java: $versionLine"
        Write-Log "java -version: $versionLine"

        if ($versionLine -match '"(\d+)') {
            $majorVersion = [int]$Matches[1]
            if ($majorVersion -eq 17 -or $majorVersion -eq 21) {
                Write-Host "  Java version $majorVersion is supported by Neo4j 5.x" -ForegroundColor Green
                Write-Log "Java $majorVersion supported by Neo4j 5.x"
                return $true
            } else {
                Write-Host "  WARNING: Java $majorVersion detected. Neo4j 5.x requires Java 17 or 21." -ForegroundColor Yellow
                Write-Host "  The service may fail to start. Install Java 17 or 21 if issues occur." -ForegroundColor Yellow
                Write-Log "Java $majorVersion detected (Neo4j 5.x requires 17 or 21)" -Level WARN
                return $true
            }
        }
        Write-Host "  Could not parse Java version, continuing..." -ForegroundColor Yellow
        Write-Log "Could not parse Java version" -Level WARN
        return $true
    } catch {
        Write-Host "  Java not found. Neo4j 5.x requires Java 17 or 21." -ForegroundColor Red
        Write-Log "Java not found: $($_.Exception.Message)" -Level ERROR
        return $true
    }
}

function Merge-Neo4jSplitZip {
    # The installer is shipped as split parts (.zip.partN, each < 50MB).
    # Merge them back into a full zip before extraction.
    $partFiles = Get-ChildItem -Path $localDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '\.part\d+$' }

    # No split parts: assume a full zip is already present, nothing to merge.
    if (-not $partFiles -or $partFiles.Count -eq 0) {
        Write-Log "No split parts (.zip.partN) found, assume full zip is present"
        return $true
    }

    # Derive the full zip name by stripping the .partN suffix.
    $fullZipName = ($partFiles[0].Name) -replace '\.part\d+$', ''
    $fullZipPath = Join-Path $localDir $fullZipName

    # A non-empty full zip already exists: skip merge (supports re-running the script).
    if ((Test-Path $fullZipPath) -and (Get-Item $fullZipPath).Length -gt 0) {
        Write-Host "  Full zip already present, skip merging: $fullZipName" -ForegroundColor DarkGray
        Write-Log "Full zip already exists, skip merge: $fullZipPath"
        return $true
    }

    # Sort by the trailing part number (natural order avoids part10 sorting before part2).
    $sortedParts = $partFiles | Sort-Object {
        if ($_.Name -match '\.part(\d+)$') { [int]$Matches[1] } else { [int]::MaxValue }
    }
    $expectedSize = ($sortedParts | Measure-Object -Property Length -Sum).Sum

    Write-Host "  Merging $($sortedParts.Count) split parts into $fullZipName ..." -ForegroundColor Cyan
    Write-Log "Merging $($sortedParts.Count) split parts into $fullZipPath (expected size: $expectedSize bytes)"

    # Concatenate parts in binary order (1MB buffer for memory-friendly streaming).
    $outStream = [System.IO.File]::Create($fullZipPath)
    $buffer = New-Object byte[] 1048576
    try {
        foreach ($part in $sortedParts) {
            Write-Host "    + $($part.Name) ($([math]::Round($part.Length / 1MB, 1)) MB)"
            Write-Log "  appending $($part.FullName)"
            $inStream = [System.IO.File]::OpenRead($part.FullName)
            try {
                while ($inStream.Position -lt $inStream.Length) {
                    $read = $inStream.Read($buffer, 0, $buffer.Length)
                    $outStream.Write($buffer, 0, $read)
                }
            } finally {
                $inStream.Close()
            }
        }
    } catch {
        Write-Host "  Merge failed: $($_.Exception.Message)" -ForegroundColor Red
        Write-Log "Merge failed: $($_.Exception.Message)" -Level ERROR
        return $false
    } finally {
        $outStream.Close()
    }

    # Size check: the merged result must equal the sum of all parts.
    $actualSize = (Get-Item $fullZipPath).Length
    if ($actualSize -ne $expectedSize) {
        Write-Host "  Merge size mismatch: expected $expectedSize bytes, got $actualSize bytes" -ForegroundColor Red
        Write-Log "Merge size mismatch: expected $expectedSize, got $actualSize" -Level ERROR
        return $false
    }

    Write-Host "  Merge completed: $fullZipName ($actualSize bytes)" -ForegroundColor Green
    Write-Log "Merge completed: $fullZipPath ($actualSize bytes)"
    return $true
}

function Extract-Neo4j {
    Write-Host "=== Extracting Neo4j ===" -ForegroundColor Green
    Write-Log "Extracting Neo4j"

    # Create directories
    New-Item -ItemType Directory -Path $neo4jDir -Force | Out-Null
    New-Item -ItemType Directory -Path $extractDir -Force | Out-Null

    # If split parts (.zip.partN) are present, merge them into a full zip first.
    if (-not (Merge-Neo4jSplitZip)) {
        Write-Host "Neo4j split-parts merge failed" -ForegroundColor Red
        return $false
    }

    # Find and extract Neo4j zip
    $neo4jZip = Get-ChildItem -Path $localDir -Name "*.zip" | Select-Object -First 1
    if (-not $neo4jZip) {
        Write-Host "Neo4j zip file not found" -ForegroundColor Red
        Write-Log "Neo4j zip file not found in $localDir" -Level ERROR
        return $false
    }

    Write-Host "Extracting $neo4jZip..."
    Write-Log "Extracting $neo4jZip to $extractDir"
    try {
        Expand-Archive -Path "$localDir\$neo4jZip" -DestinationPath $extractDir -Force
        Write-Log "Expand-Archive completed"
    } catch {
        Write-Log "Expand-Archive failed: $($_.Exception.Message)" -Level ERROR
    }

    # Verify extraction
    if (Test-Path $neo4jHome) {
        Write-Host "Neo4j extracted successfully" -ForegroundColor Green
        Write-Log "Neo4j extracted to $neo4jHome"
        return $true
    } else {
        Write-Host "Neo4j extraction failed" -ForegroundColor Red
        Write-Log "Neo4j extraction failed: $neo4jHome not found" -Level ERROR
        return $false
    }
}

function Configure-Neo4j {
    Write-Host "=== Configuring Neo4j ===" -ForegroundColor Green
    Write-Log "Configuring Neo4j"
    
    # Define Neo4j data directories
    $neo4jConfigFile = "$neo4jHome\conf\neo4j.conf"
    $neo4jDataDir = "$projectRoot\backend\data\neo4j\data"
    $neo4jLogsDir = "$projectRoot\backend\data\neo4j\logs"

    # Create necessary directories
    New-Item -ItemType Directory -Path "$projectRoot\backend\data\neo4j" -Force | Out-Null
    New-Item -ItemType Directory -Path $neo4jDataDir -Force | Out-Null
    New-Item -ItemType Directory -Path $neo4jLogsDir -Force | Out-Null
    
    # Modify neo4j.conf file
    if (Test-Path $neo4jConfigFile) {
        Write-Host "Modifying neo4j.conf file..."

        # Read the config file
        $configContent = Get-Content -Path $neo4jConfigFile

        $neo4jDataDirUnix = $neo4jDataDir -replace '\\', '/'
        $neo4jLogsDirUnix = $neo4jLogsDir -replace '\\', '/'

        # Neo4j 5.x uses server.directories.*, 4.x uses dbms.directories.*
        # Try 5.x patterns first, then 4.x patterns, then append if neither matched
        $dataReplaced = $false
        $logsReplaced = $false

        # Update data directory
        $configContent = $configContent | ForEach-Object {
            if ($_ -match "^#?server\.directories\.data=") {
                $dataReplaced = $true
                "server.directories.data=$neo4jDataDirUnix"
            } elseif ($_ -match "^#?dbms\.directories\.data=") {
                $dataReplaced = $true
                "server.directories.data=$neo4jDataDirUnix"
            } else { $_ }
        }

        # Update logs directory
        $configContent = $configContent | ForEach-Object {
            if ($_ -match "^#?server\.directories\.logs=") {
                $logsReplaced = $true
                "server.directories.logs=$neo4jLogsDirUnix"
            } elseif ($_ -match "^#?dbms\.directories\.logs=") {
                $logsReplaced = $true
                "server.directories.logs=$neo4jLogsDirUnix"
            } else { $_ }
        }

        # Update transaction logs root (may not exist in all versions)
        $txLogsReplaced = $false
        $configContent = $configContent | ForEach-Object {
            if ($_ -match "^#?server\.directories\.transaction\.logs\.root=") {
                $txLogsReplaced = $true
                "server.directories.transaction.logs.root=$neo4jDataDirUnix/transactions"
            } elseif ($_ -match "^#?dbms\.directories\.transaction\.logs\.root=") {
                $txLogsReplaced = $true
                "server.directories.transaction.logs.root=$neo4jDataDirUnix/transactions"
            } else { $_ }
        }

        # Append any properties that were not found in the config
        $appendLines = @()
        if (-not $dataReplaced) {
            $appendLines += "server.directories.data=$neo4jDataDirUnix"
        }
        if (-not $logsReplaced) {
            $appendLines += "server.directories.logs=$neo4jLogsDirUnix"
        }
        if (-not $txLogsReplaced) {
            $appendLines += "server.directories.transaction.logs.root=$neo4jDataDirUnix/transactions"
        }
        if ($appendLines.Count -gt 0) {
            $configContent += ""
            $configContent += "# Custom directories (appended by install script)"
            $configContent += $appendLines
        }

        # Write the updated config file
        Set-Content -Path $neo4jConfigFile -Value $configContent

        Write-Host "Neo4j configuration updated successfully" -ForegroundColor Green
        Write-Log "Neo4j configuration updated: data=$neo4jDataDir, logs=$neo4jLogsDir"
        return $true
    } else {
        Write-Host "Neo4j config file not found" -ForegroundColor Red
        Write-Log "Neo4j config file not found: $neo4jConfigFile" -Level ERROR
        return $false
    }
}

function Install-Neo4jService {
    Write-Host "=== Installing Neo4j Service ===" -ForegroundColor Green
    Write-Log "Installing Neo4j service"

    if (-not (Test-Path $neo4jBin)) {
        Write-Host "Neo4j executable not found" -ForegroundColor Red
        Write-Log "Neo4j executable not found: $neo4jBin" -Level ERROR
        return $false
    }

    # Check if service already exists
    $existingSvc = Get-Service -Name "Neo4j" -ErrorAction SilentlyContinue
    if (-not $existingSvc) {
        $existingSvc = Get-Service | Where-Object { $_.DisplayName -eq 'Neo4j' }
    }
    if ($existingSvc) {
        Write-Host "Neo4j service already installed, skipping..." -ForegroundColor Yellow
        Write-Log "Neo4j service already installed, skipping"
        return $true
    }

    # Install service (Neo4j 5.x: "windows-service install", 4.x: "install-service")
    $neo4jBinDir = Split-Path $neo4jBin -Parent
    Set-Location $neo4jBinDir
    Write-Log "Running neo4j.bat windows-service install"
    $exitCode = Invoke-LoggedProcess -FilePath ".\neo4j.bat" -ArgumentList @("windows-service", "install") -WorkingDirectory $neo4jBinDir -UseCmdShell

    if ($exitCode -ne 0) {
        Write-Host "Retrying with legacy install-service command..."
        Write-Log "Retrying with neo4j.bat install-service"
        $exitCode = Invoke-LoggedProcess -FilePath ".\neo4j.bat" -ArgumentList @("install-service") -WorkingDirectory $neo4jBinDir -UseCmdShell
    }
    Set-Location $currentDir

    if ($exitCode -eq 0) {
        Write-Host "Neo4j service installed successfully" -ForegroundColor Green
        Write-Log "Neo4j service installed successfully"
        return $true
    } else {
        Write-Host "Neo4j service installation failed" -ForegroundColor Red
        Write-Log "Neo4j service installation failed (exit code $exitCode)" -Level ERROR
        return $false
    }
}

function Set-Neo4jHome {
    Write-Host "=== Setting NEO4J_HOME ===" -ForegroundColor Green
    Write-Log "Setting NEO4J_HOME=$neo4jHome"

    # Set NEO4J_HOME (must be done before service installation)
    [Environment]::SetEnvironmentVariable("NEO4J_HOME", $neo4jHome, "User")
    $env:NEO4J_HOME = $neo4jHome
    Write-Host "Set NEO4J_HOME to $neo4jHome"

    return $true
}

function Initialize-Neo4j {
    Write-Host "=== Initializing Neo4j ===" -ForegroundColor Green
    Write-Log "Initializing Neo4j (setting initial password)"

    # Set initial password (must be done before the database is started for the first time)
    $neo4jAdmin = "$neo4jHome\bin\neo4j-admin.bat"
    if (Test-Path $neo4jAdmin) {
        $env:NEO4J_ACCEPT_LICENSE_AGREEMENT = "yes"
        $neo4jAdminDir = Split-Path $neo4jAdmin -Parent
        # Neo4j 5.x uses "dbms set-initial-password", 4.x uses "set-initial-password"
        Write-Log "Running neo4j-admin dbms set-initial-password"
        $exitCode = Invoke-LoggedProcess -FilePath $neo4jAdmin -ArgumentList @("dbms", "set-initial-password", "1234qwer") -WorkingDirectory $neo4jAdminDir -UseCmdShell

        if ($exitCode -ne 0) {
            Write-Host "Retrying with legacy set-initial-password command..."
            Write-Log "Retrying with neo4j-admin set-initial-password"
            $exitCode = Invoke-LoggedProcess -FilePath $neo4jAdmin -ArgumentList @("set-initial-password", "1234qwer") -WorkingDirectory $neo4jAdminDir -UseCmdShell
        }

        if ($exitCode -eq 0) {
            Write-Host "Initial password set successfully" -ForegroundColor Green
            Write-Log "Neo4j initial password set successfully"
            return $true
        }
    }

    Write-Host "Neo4j initialization failed" -ForegroundColor Red
    Write-Log "Neo4j initialization failed" -Level ERROR
    return $false
}

function Start-Neo4jService {
    Write-Host "=== Starting Neo4j Service ===" -ForegroundColor Green
    Write-Log "Starting Neo4j service"

    # Neo4j 5.x: use Windows service management (neo4j.bat only supports install/uninstall)
    $svc = Get-Service -Name "Neo4j" -ErrorAction SilentlyContinue
    if (-not $svc) {
        $svc = Get-Service | Where-Object { $_.DisplayName -eq 'Neo4j' }
    }

    if ($svc) {
        Write-Host "Starting Neo4j service ($($svc.Name))..."
        Write-Log "Issuing net start $($svc.Name) via wscript UAC elevation"

        # Service control requires admin privileges, use silent elevation
        $tempBat = [System.IO.Path]::GetTempFileName() + ".bat"
        Set-Content -Path $tempBat -Value "@echo off`r`nnet start `"$($svc.Name)`""
        $tempVbs = [System.IO.Path]::GetTempFileName() + ".vbs"
        Set-Content -Path $tempVbs -Value "CreateObject(""WScript.Shell"").Run ""$tempBat"", 0, True"
        try {
            Start-Process -FilePath "wscript.exe" -ArgumentList "`"$tempVbs`"" -Verb RunAs -Wait
        } finally {
            Remove-Item $tempBat -Force -ErrorAction SilentlyContinue
            Remove-Item $tempVbs -Force -ErrorAction SilentlyContinue
        }

        # Wait and verify
        Start-Sleep -Seconds 5
        $svc.Refresh()
        if ($svc.Status -eq 'Running') {
            Write-Host "Neo4j service started" -ForegroundColor Green
            Write-Log "Neo4j service started successfully"
            return $true
        } else {
            Write-Host "Neo4j service status: $($svc.Status)" -ForegroundColor Yellow
            Write-Host "Check Neo4j logs for details: $neo4jHome\logs\neo4j.log" -ForegroundColor Yellow
            Write-Log "Neo4j service status: $($svc.Status), check $neo4jHome\logs\neo4j.log" -Level WARN
            return $false
        }
    } else {
        Write-Host "Neo4j service not found" -ForegroundColor Red
        Write-Log "Neo4j service not found" -Level ERROR
        return $false
    }
}

function Check-Neo4jStatus {
    Write-Host "=== Checking Neo4j Status ===" -ForegroundColor Green
    Write-Log "Checking Neo4j status"

    $svc = Get-Service -Name "Neo4j" -ErrorAction SilentlyContinue
    if (-not $svc) {
        $svc = Get-Service | Where-Object { $_.DisplayName -eq 'Neo4j' }
    }

    if ($svc) {
        Write-Host "Neo4j status: $($svc.Status)"
        Write-Log "Neo4j service status: $($svc.Status)"
        return ($svc.Status -eq 'Running')
    } else {
        Write-Host "Neo4j service not found" -ForegroundColor Red
        Write-Log "Neo4j service not found" -Level ERROR
        return $false
    }
}

# Main install process
$neo4jSuccess = $false
Check-JavaVersion
if (Extract-Neo4j) {
    if (Configure-Neo4j) {
        if (Set-Neo4jHome) {
            if (Initialize-Neo4j) {
                if (Install-Neo4jService) {
                    if (Start-Neo4jService) {
                        Start-Sleep -Seconds 5
                        if (Check-Neo4jStatus) {
                            Write-Host "Neo4j installation completed successfully!" -ForegroundColor Green
                            Write-Log "Neo4j installation completed successfully"
                            $neo4jSuccess = $true
                        } else {
                            Write-Host "Neo4j installation completed but service not running" -ForegroundColor Yellow
                            Write-Log "Neo4j installation completed but service not running" -Level WARN
                            $neo4jSuccess = $false
                        }
                    }
                }
            }
        }
    }
}

return $neo4jSuccess
