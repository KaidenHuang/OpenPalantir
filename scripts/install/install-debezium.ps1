<#
.SYNOPSIS
Installs Debezium Server and connector plugins from local packages

.DESCRIPTION
This script extracts the Debezium Server distribution and connector plugins
from local packages into the extracted/ directory, then generates
application.properties for each connector.
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
$debeziumDir = "$dependenciesDir\debezium"
$extractDir = "$debeziumDir\extracted"
$localDir = "$debeziumDir\local"

Initialize-LogFile -Action "install-debezium" -LogFilePath $LogFilePath

function Get-TarFlags {
    # Detect tar implementation: GNU tar needs --force-local for Windows paths with drive letters
    # Resolve full path to ensure the same tar is used for both detection and extraction
    $tarCmd = (Get-Command tar -ErrorAction SilentlyContinue).Source
    if (-not $tarCmd) { $tarCmd = "tar" }
    $tarVersionOutput = & $tarCmd --version 2>&1 | Select-Object -First 1
    Write-Log "tar path: $tarCmd"
    Write-Log "tar version: $tarVersionOutput"
    $isGnuTar = $tarVersionOutput -match "GNU tar"
    if ($isGnuTar) {
        Write-Host "  Using GNU tar at $tarCmd (--force-local enabled)"
        return @{ TarPath = $tarCmd; ForceLocal = "--force-local" }
    } else {
        Write-Host "  Using BSD tar at $tarCmd (Windows built-in)"
        return @{ TarPath = $tarCmd; ForceLocal = "" }
    }
}

function Ensure-DebeziumPackages {
    Write-Host "=== Preparing Debezium Packages ===" -ForegroundColor Green
    Write-Log "Preparing Debezium packages"

    # Ensure local directory exists
    if (-not (Test-Path $localDir)) {
        New-Item -ItemType Directory -Path $localDir -Force | Out-Null
        Write-Host "  Created directory: $localDir"
        Write-Log "Created directory: $localDir"
    }

    # Download manifest: display name, file name, Maven artifact path segment.
    # All artifacts live under https://repo1.maven.org/maven2/io/debezium/<artifact>/3.5.2.Final/<file>
    $mavenBase = "https://repo1.maven.org/maven2/io/debezium"
    $version = "3.5.2.Final"
    $packages = @(
        @{ Name = "Debezium Server distribution"; File = "debezium-server-dist-$version.tar.gz"; Artifact = "debezium-server-dist" },
        @{ Name = "MySQL connector";              File = "debezium-connector-mysql-$version-plugin.tar.gz";      Artifact = "debezium-connector-mysql" },
        @{ Name = "Oracle connector";             File = "debezium-connector-oracle-$version-plugin.tar.gz";     Artifact = "debezium-connector-oracle" },
        @{ Name = "PostgreSQL connector";         File = "debezium-connector-postgres-$version-plugin.tar.gz";   Artifact = "debezium-connector-postgres" },
        @{ Name = "SQL Server connector";         File = "debezium-connector-sqlserver-$version-plugin.tar.gz";  Artifact = "debezium-connector-sqlserver" }
    )

    # WebClient avoids the Invoke-WebRequest progress-bar overhead that cripples
    # large downloads on PowerShell 5.1; synchronous and reliable for ~650MB files.
    $webClient = New-Object System.Net.WebClient

    foreach ($pkg in $packages) {
        $targetPath = Join-Path $localDir $pkg.File
        $url = "$mavenBase/$($pkg.Artifact)/$version/$($pkg.File)"

        # Idempotent: skip if already present and non-empty
        if (Test-Path $targetPath) {
            $existing = Get-Item $targetPath
            if ($existing.Length -gt 0) {
                Write-Host "  [$($pkg.Name)] $($pkg.File) already present, skipping" -ForegroundColor DarkGray
                Write-Log "$($pkg.File) already present, skipping"
                continue
            }
        }

        Write-Host "  [$($pkg.Name)] Downloading $($pkg.File)..." -ForegroundColor Cyan
        Write-Host "    from $url" -ForegroundColor DarkGray
        Write-Log "Downloading $url"
        try {
            $webClient.DownloadFile($url, $targetPath)
        } catch {
            Write-Host "  Failed to download $($pkg.File): $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "  Please check your network connection and Maven Central availability." -ForegroundColor Red
            Write-Log "Download failed: $url - $($_.Exception.Message)" -Level ERROR
            return $false
        }

        $downloaded = Get-Item $targetPath
        if ($downloaded.Length -eq 0) {
            Write-Host "  Downloaded file is empty: $($pkg.File)" -ForegroundColor Red
            Write-Log "Downloaded file is empty: $($pkg.File)" -Level ERROR
            return $false
        }

        # Verify integrity against the .sha256 published alongside each artifact
        try {
            $remoteHashRaw = $webClient.DownloadString("$url.sha256").Trim()
            # Maven .sha256 is "<hash>" or "<hash>  <filename>"; take the first token
            $remoteHash = ($remoteHashRaw -split '\s+')[0].ToLower()
            $localHash = (Get-FileHash -Path $targetPath -Algorithm SHA256).Hash.ToLower()
            if ($localHash -ne $remoteHash) {
                Write-Host "  SHA256 verification failed for $($pkg.File)" -ForegroundColor Red
                Write-Host "    expected: $remoteHash" -ForegroundColor Red
                Write-Host "    actual:   $localHash" -ForegroundColor Red
                Write-Log "SHA256 mismatch for $($pkg.File): expected $remoteHash actual $localHash" -Level ERROR
                Remove-Item -Path $targetPath -Force -ErrorAction SilentlyContinue
                return $false
            }
            $sizeMB = [Math]::Round($downloaded.Length / 1MB, 1)
            Write-Host "  [$($pkg.Name)] $($pkg.File) downloaded ($sizeMB MB, SHA256 verified)" -ForegroundColor Green
            Write-Log "$($pkg.File) downloaded ($sizeMB MB, SHA256 verified)"
        } catch {
            Write-Host "  SHA256 checksum unavailable for $($pkg.File), proceeding without verification" -ForegroundColor Yellow
            Write-Log "SHA256 checksum unavailable for $($pkg.File): $($_.Exception.Message)" -Level WARN
        }
    }

    Write-Host "  All Debezium packages ready in $localDir" -ForegroundColor Green
    Write-Log "All Debezium packages ready"
    return $true
}

function Extract-DebeziumServer {
    Write-Host "=== Extracting Debezium Server ===" -ForegroundColor Green
    Write-Log "Extracting Debezium Server"

    New-Item -ItemType Directory -Path $extractDir -Force | Out-Null

    # Find Server distribution (debezium-server-dist-*.tar.gz)
    $serverDist = Get-ChildItem -Path $localDir -Filter "debezium-server-dist-*.tar.gz" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $serverDist) {
        Write-Host "  Debezium Server distribution not found in $localDir" -ForegroundColor Red
        Write-Host "  Expected: debezium-server-dist-*.tar.gz" -ForegroundColor Yellow
        Write-Log "debezium-server-dist-*.tar.gz not found in $localDir" -Level ERROR
        return $false
    }

    Write-Host "  Found: $($serverDist.Name)"
    Write-Log "Found server distribution: $($serverDist.Name)"

    # Extract via temp directory
    $tempDir = "$extractDir\_temp_server"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    Write-Log "Extracting $($serverDist.FullName) to $tempDir"
    $tarArgs = @()
    if ($tarFlags.ForceLocal) { $tarArgs += $tarFlags.ForceLocal }
    $tarArgs += @("-xzf", "$($serverDist.FullName)", "-C", "$tempDir")
    $exitCode = Invoke-LoggedProcess -FilePath $tarFlags.TarPath -ArgumentList $tarArgs

    if ($exitCode -ne 0) {
        Write-Host "  Failed to extract Debezium Server" -ForegroundColor Red
        Write-Log "tar extraction failed (exit code $exitCode)" -Level ERROR
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }

    # Flatten single-level subdirectory: move contents of debezium-server/ into extracted/
    $subDirs = Get-ChildItem -Path $tempDir -Directory
    $sourceDir = if ($subDirs.Count -eq 1) { $subDirs[0].FullName } else { $tempDir }

    Get-ChildItem -Path $sourceDir | ForEach-Object {
        $targetPath = Join-Path $extractDir $_.Name
        if (Test-Path $targetPath) {
            Remove-Item -Path $targetPath -Recurse -Force
        }
        Move-Item -Path $_.FullName -Destination $extractDir
    }
    Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue

    # Verify
    $runBat = "$extractDir\run.bat"
    if (Test-Path $runBat) {
        # Patch run.bat: fix variable name typo (LIB_CONFIG -> LIB_CONFIG_PATH)
        # and missing SET keyword on the ENABLE_DEBEZIUM_SCRIPTING line
        $runBatContent = Get-Content -Path $runBat -Raw
        $runBatContent = $runBatContent -replace 'SET LIB_CONFIG=config\\lib', 'SET LIB_CONFIG_PATH=config\lib'
        $runBatContent = $runBatContent -replace '"true" LIB_PATH=', '"true" SET LIB_PATH='
        Set-Content -Path $runBat -Value $runBatContent -NoNewline
        Write-Host "  Patched run.bat (fixed LIB_CONFIG_PATH variable and SET keyword)" -ForegroundColor Cyan
        Write-Log "Patched run.bat (fixed LIB_CONFIG_PATH and SET keyword)"

        $libJars = Get-ChildItem -Path "$extractDir\lib" -Filter "*.jar" -ErrorAction SilentlyContinue
        Write-Host "  Debezium Server extracted: run.bat found, $($libJars.Count) runtime JAR(s) in lib/" -ForegroundColor Green
        Write-Log "Debezium Server extracted: run.bat found, $($libJars.Count) runtime JAR(s)"
        return $true
    } else {
        Write-Host "  Extraction failed: run.bat not found" -ForegroundColor Red
        Write-Log "Extraction failed: run.bat not found in $extractDir" -Level ERROR
        return $false
    }
}

function Extract-DebeziumConnectors {
    Write-Host "=== Extracting Debezium Connectors ===" -ForegroundColor Green
    Write-Log "Extracting Debezium Connectors"

    # Ensure connectors/ directory exists
    $connectorsDir = "$extractDir\connectors"
    New-Item -ItemType Directory -Path $connectorsDir -Force | Out-Null

    # Find connector packages (*.tar.gz excluding server-dist)
    $connectors = Get-ChildItem -Path $localDir -Filter "debezium-connector-*.tar.gz" -ErrorAction SilentlyContinue
    if (-not $connectors -or $connectors.Count -eq 0) {
        Write-Host "  No connector packages found in $localDir" -ForegroundColor Red
        Write-Log "No connector packages found in $localDir" -Level ERROR
        return $false
    }

    Write-Host "  Found $($connectors.Count) connector package(s)"
    Write-Log "Found $($connectors.Count) connector package(s)"

    $extractedCount = 0
    foreach ($connector in $connectors) {
        Write-Host "  Extracting $($connector.Name)..."
        Write-Log "Extracting $($connector.Name)"

        $tempDir = "$extractDir\_temp_connector"
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

        $tarArgs = @()
        if ($tarFlags.ForceLocal) { $tarArgs += $tarFlags.ForceLocal }
        $tarArgs += @("-xzf", "$($connector.FullName)", "-C", "$tempDir")
        $exitCode = Invoke-LoggedProcess -FilePath $tarFlags.TarPath -ArgumentList $tarArgs

        if ($exitCode -ne 0) {
            Write-Host "    Failed to extract $($connector.Name)" -ForegroundColor Yellow
            Write-Log "tar extraction of $($connector.Name) failed (exit code $exitCode)" -Level WARN
            Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
            continue
        }

        # Move extracted top-level directory into connectors/ (keep connector subdirectory)
        Get-ChildItem -Path $tempDir | ForEach-Object {
            $targetPath = Join-Path $connectorsDir $_.Name
            if (Test-Path $targetPath) {
                Remove-Item -Path $targetPath -Recurse -Force
            }
            Move-Item -Path $_.FullName -Destination $connectorsDir
        }
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue

        $extractedCount++
    }

    # Verify extraction (only count debezium-connector-* directories)
    $connectorDirs = Get-ChildItem -Path $connectorsDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "^debezium-connector-" }
    if ($connectorDirs -and $connectorDirs.Count -gt 0) {
        $totalJars = 0
        foreach ($dir in $connectorDirs) {
            $dirJars = Get-ChildItem -Path $dir.FullName -Filter "*.jar" -ErrorAction SilentlyContinue
            $jarCount = if ($dirJars) { $dirJars.Count } else { 0 }
            $totalJars += $jarCount
            Write-Host "    connectors/$($dir.Name)/ - $jarCount JAR(s)"
        }
        Write-Host "  $extractedCount connector(s) extracted, $totalJars JAR file(s) total" -ForegroundColor Green
        Write-Log "$extractedCount connector(s) extracted, $totalJars JAR file(s) total"
        return $true
    } else {
        Write-Host "  Warning: no connector directories found" -ForegroundColor Yellow
        Write-Log "No connector directories found after extraction" -Level WARN
        return $extractedCount -gt 0
    }
}

function Configure-Debezium {
    Write-Host "=== Configuring Debezium ===" -ForegroundColor Green
    Write-Log "Configuring Debezium"

    # Create data directories
    $debeziumDataDir = "$projectRoot\backend\data\debezium"
    New-Item -ItemType Directory -Path $debeziumDataDir -Force | Out-Null
    New-Item -ItemType Directory -Path "$debeziumDataDir\offsets" -Force | Out-Null
    Write-Host "  Data directories created at $debeziumDataDir"

    # Ensure config/ directory exists (Debezium Server uses config/, not conf/)
    $configDir = "$extractDir\config"
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null

    # Common config sections shared by all connectors
    $commonConfig = @"
# ---- Sink: 写入 Redis Streams ----
debezium.sink.type=redis
debezium.sink.redis.address=127.0.0.1:6379
debezium.sink.redis.stream-type=stream

# ---- 快照模式 ----
# never = 跳过初始快照（全量导入已覆盖），从当前 binlog 位点开始
debezium.source.snapshot.mode=never

# ---- 偏移量存储（Debezium 内部断点）----
debezium.source.offset.storage=org.apache.kafka.connect.storage.FileOffsetBackingStore
debezium.source.offset.storage.file.filename=data/debezium/offsets/offsets.dat
debezium.source.offset.flush.interval.ms=5000

# ---- 日志 ----
quarkus.log.level=INFO
quarkus.log.console.json=false
"@

    # Connector-specific source configurations
    $sourceConfigs = @{
        "mysql" = @"

# ---- Source: MySQL ----
debezium.source.connector.class=io.debezium.connector.mysql.MySqlConnector
debezium.source.database.hostname=127.0.0.1
debezium.source.database.port=3306
debezium.source.database.user=cdc_user
debezium.source.database.password=cdc_password
debezium.source.database.server.id=1
debezium.source.topic.prefix=openpalantir
debezium.source.database.include.list=employees
debezium.source.table.include.list=employees.employees,employees.departments,employees.dept_emp
"@
        "postgres" = @"

# ---- Source: PostgreSQL ----
debezium.source.connector.class=io.debezium.connector.postgresql.PostgresConnector
debezium.source.database.hostname=127.0.0.1
debezium.source.database.port=5432
debezium.source.database.user=cdc_user
debezium.source.database.password=cdc_password
debezium.source.database.dbname=employees
debezium.source.topic.prefix=openpalantir
debezium.source.table.include.list=public.employees,public.departments,public.dept_emp
debezium.source.plugin.name=pgoutput
"@
        "oracle" = @"

# ---- Source: Oracle ----
debezium.source.connector.class=io.debezium.connector.oracle.OracleConnector
debezium.source.database.hostname=127.0.0.1
debezium.source.database.port=1521
debezium.source.database.user=cdc_user
debezium.source.database.password=cdc_password
debezium.source.database.dbname=ORCLCDB
debezium.source.database.pdb.name=ORCLPDB1
debezium.source.topic.prefix=openpalantir
debezium.source.schema.include.list=HR
"@
        "sqlserver" = @"

# ---- Source: SQL Server ----
debezium.source.connector.class=io.debezium.connector.sqlserver.SqlServerConnector
debezium.source.database.hostname=127.0.0.1
debezium.source.database.port=1433
debezium.source.database.user=cdc_user
debezium.source.database.password=cdc_password
debezium.source.database.dbname=master
debezium.source.topic.prefix=openpalantir
debezium.source.schema.include.list=dbo
"@
    }

    # Generate application.properties for each connector in config/
    $connectorsDir = "$extractDir\connectors"
    $connectorDirs = Get-ChildItem -Path $connectorsDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "^debezium-connector-" }
    $configCount = 0

    foreach ($dir in $connectorDirs) {
        # Detect connector type from directory name
        $connectorType = $null
        if ($dir.Name -match "mysql") { $connectorType = "mysql" }
        elseif ($dir.Name -match "postgres") { $connectorType = "postgres" }
        elseif ($dir.Name -match "oracle") { $connectorType = "oracle" }
        elseif ($dir.Name -match "sqlserver") { $connectorType = "sqlserver" }

        if ($connectorType -and $sourceConfigs.ContainsKey($connectorType)) {
            $header = "# ============================================================`n# Debezium Server - $connectorType Connector`n# ============================================================`n"
            $configContent = $header + $commonConfig + $sourceConfigs[$connectorType]

            # Write config to config/application.properties.{connectorType}
            $configFile = "$configDir\application.properties.$connectorType"
            $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($configFile, $configContent, $utf8NoBom)
            Write-Host "  Generated config/application.properties.$connectorType" -ForegroundColor Green
            $configCount++
        } else {
            Write-Host "  Unknown connector type for $($dir.Name), skipping config" -ForegroundColor Yellow
        }
    }

    # Create default application.properties (copy from mysql config)
    if ($configCount -gt 0) {
        $defaultConfig = "$configDir\application.properties"
        $mysqlConfig = "$configDir\application.properties.mysql"
        if (Test-Path $mysqlConfig) {
            Copy-Item -Path $mysqlConfig -Destination $defaultConfig -Force
            Write-Host "  Default config/application.properties (mysql) created" -ForegroundColor Green
        }
        Write-Host "  $configCount configuration file(s) generated" -ForegroundColor Green
        Write-Log "$configCount Debezium configuration file(s) generated"
        return $true
    } else {
        Write-Host "  No configuration files generated" -ForegroundColor Yellow
        Write-Log "No Debezium configuration files generated" -Level WARN
        return $false
    }
}

function Check-DebeziumStatus {
    Write-Host "=== Checking Debezium Setup ===" -ForegroundColor Green

    # Check Server runtime
    $runBat = "$extractDir\run.bat"
    if (Test-Path $runBat) {
        $libJars = Get-ChildItem -Path "$extractDir\lib" -Filter "*.jar" -ErrorAction SilentlyContinue
        $libCount = if ($libJars) { $libJars.Count } else { 0 }
        Write-Host "  Server runtime: run.bat found, $libCount JAR(s) in lib/" -ForegroundColor Green
    } else {
        Write-Host "  Server runtime: run.bat NOT found" -ForegroundColor Red
    }

    # Check connectors (only debezium-connector-* directories)
    $connectorsDir = "$extractDir\connectors"
    $connectorDirs = Get-ChildItem -Path $connectorsDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "^debezium-connector-" }
    if ($connectorDirs) {
        Write-Host "  Connectors ($($connectorDirs.Count)):" -ForegroundColor Green
        foreach ($dir in $connectorDirs) {
            $dirJars = Get-ChildItem -Path $dir.FullName -Filter "*.jar" -ErrorAction SilentlyContinue
            $jarCount = if ($dirJars) { $dirJars.Count } else { 0 }
            Write-Host "    connectors/$($dir.Name)/ - $jarCount JAR(s)"
        }
    } else {
        Write-Host "  Connectors: none found" -ForegroundColor Yellow
    }

    # Check configs
    $configFiles = Get-ChildItem -Path "$extractDir\config" -Filter "application.properties*" -ErrorAction SilentlyContinue
    if ($configFiles) {
        Write-Host "  Configs: $($configFiles.Count) file(s)" -ForegroundColor Green
        foreach ($f in $configFiles) {
            Write-Host "    config/$($f.Name)"
        }
    }

    return (Test-Path $runBat)
}

function Start-DebeziumService {
    Write-Host "=== Starting Debezium Server ===" -ForegroundColor Green
    Write-Log "Starting Debezium Server"

    $runBat = "$extractDir\run.bat"
    if (-not (Test-Path $runBat)) {
        Write-Host "  run.bat not found, cannot start Debezium Server" -ForegroundColor Red
        return $false
    }

    # Check JAVA_HOME (required by run.bat)
    if (-not $env:JAVA_HOME) {
        $javaHome = $null
        # Method 1: query java itself for the real home path
        # Temporarily set Continue because java -version writes to stderr
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $javaOutput = & java -XshowSettings:properties -version 2>&1 | Out-String
            if ($javaOutput -match "java\.home\s*=\s*(.+)") {
                $javaHome = $Matches[1].Trim()
            }
        } catch { }
        $ErrorActionPreference = $prevEAP

        if ($javaHome -and (Test-Path "$javaHome\bin\java.exe")) {
            $env:JAVA_HOME = $javaHome
            [Environment]::SetEnvironmentVariable("JAVA_HOME", $javaHome, "User")
            Write-Host "  JAVA_HOME not set, auto-detected: $javaHome" -ForegroundColor Yellow
            Write-Log "JAVA_HOME auto-detected: $javaHome"
        } else {
            Write-Host "  JAVA_HOME not set and Java not found in PATH" -ForegroundColor Red
            Write-Host "  Please set JAVA_HOME before starting Debezium Server" -ForegroundColor Red
            return $false
        }
    }

    # Check Redis connectivity (Debezium sinks to Redis Streams)
    try {
        $tcpTest = Test-NetConnection -ComputerName 127.0.0.1 -Port 6379 -WarningAction SilentlyContinue
        if (-not $tcpTest.TcpTestSucceeded) {
            Write-Host "  Redis not reachable at 127.0.0.1:6379, Debezium Server may fail to start" -ForegroundColor Yellow
            Write-Host "  Start Redis first: .\scripts\service\start-services.ps1" -ForegroundColor Yellow
        }
    } catch {
        # Skip check if Test-NetConnection is unavailable
    }

    $debeziumDataDir = "$projectRoot\backend\data\debezium"
    $logFile = "$debeziumDataDir\debezium.log"
    $errFile = "$debeziumDataDir\debezium-error.log"
    Write-Log "Starting Debezium Server: $runBat (logs: $logFile, errors: $errFile)"
    Start-Process -FilePath $runBat -WorkingDirectory $extractDir `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError $errFile `
        -WindowStyle Hidden
    Write-Host "  Debezium Server start command issued" -ForegroundColor Green
    Write-Host "  Logs: $logFile" -ForegroundColor Cyan
    Write-Host "  Errors: $errFile" -ForegroundColor Cyan
    return $true
}

function Check-DebeziumServiceStatus {
    Write-Host "=== Checking Debezium Service Status ===" -ForegroundColor Green
    Write-Log "Checking Debezium service status"

    Write-Host "  Waiting up to 30 seconds for Debezium Server to start..."
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 2
        try {
            $javaProcesses = Get-Process -Name "java" -ErrorAction SilentlyContinue
            if ($javaProcesses) {
                foreach ($proc in $javaProcesses) {
                    try {
                        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
                        if ($cmdLine -match "debezium") {
                            Write-Host "  Debezium Server is running (PID: $($proc.Id))" -ForegroundColor Green
                            Write-Log "Debezium Server is running (PID: $($proc.Id))"
                            return $true
                        }
                    } catch { }
                }
            }
        } catch { }
        Write-Host "    ...polling ($([Math]::Floor($i * 2 + 2))s)"
    }

    Write-Host "  Debezium Server process not detected" -ForegroundColor Yellow
    Write-Log "Debezium Server process not detected after 30s" -Level WARN
    Write-Host "  Possible causes:" -ForegroundColor Yellow
    Write-Host "    - Redis is not running (start with: .\scripts\service\start-services.ps1)" -ForegroundColor Yellow
    Write-Host "    - Source database is not running or not configured" -ForegroundColor Yellow
    Write-Host "    - Check application.properties in config/ for connection settings" -ForegroundColor Yellow

    # Show error log if available
    $errFile = "$projectRoot\backend\data\debezium\debezium-error.log"
    if (Test-Path $errFile) {
        $errContent = Get-Content -Path $errFile -Raw -ErrorAction SilentlyContinue
        if ($errContent -and $errContent.Trim()) {
            Write-Host ""
            Write-Host "  --- Error log (debezium-error.log) ---" -ForegroundColor Red
            $lines = $errContent -split "`n" | Select-Object -Last 20
            foreach ($line in $lines) {
                Write-Host "    $line" -ForegroundColor Red
            }
            Write-Host "  --- End of error log ---" -ForegroundColor Red
        }
    }
    $logFile = "$projectRoot\backend\data\debezium\debezium.log"
    if (Test-Path $logFile) {
        $logContent = Get-Content -Path $logFile -Raw -ErrorAction SilentlyContinue
        if ($logContent -and $logContent.Trim()) {
            Write-Host ""
            Write-Host "  --- Debezium log (last 20 lines) ---" -ForegroundColor Yellow
            $lines = $logContent -split "`n" | Select-Object -Last 20
            foreach ($line in $lines) {
                Write-Host "    $line" -ForegroundColor Yellow
            }
            Write-Host "  --- End of log ---" -ForegroundColor Yellow
        }
    }
    return $false
}

# Main install process
$tarFlags = Get-TarFlags

# Download packages from Maven Central on first run (idempotent)
if (-not (Ensure-DebeziumPackages)) {
    Write-Host "Debezium installation aborted: failed to prepare packages" -ForegroundColor Red
    Write-Log "Debezium installation aborted: package preparation failed"
    return $false
}

$debeziumSuccess = $false
if (Extract-DebeziumServer) {
    if (Extract-DebeziumConnectors) {
        if (Configure-Debezium) {
            Check-DebeziumStatus | Out-Null
            if (Start-DebeziumService) {
                $serviceRunning = Check-DebeziumServiceStatus
                if ($serviceRunning) {
                    Write-Host "Debezium installation completed successfully!" -ForegroundColor Green
                    Write-Log "Debezium installation completed successfully"
                    $debeziumSuccess = $true
                } else {
                    Write-Host "Debezium installed and start command issued, but process not yet detected" -ForegroundColor Yellow
                    Write-Log "Debezium installed, start command issued but process not yet detected" -Level WARN
                    $debeziumSuccess = $true
                }
            }
        }
    }
}

return $debeziumSuccess
