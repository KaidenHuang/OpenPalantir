<#
.SYNOPSIS
Shared logging helpers for install/uninstall scripts

.DESCRIPTION
Provides Initialize-LogFile, Write-Log, and Invoke-LoggedProcess functions.
Dot-source this file at the top of every install/uninstall script:
    . "$PSScriptRoot\..\install-uninstall-helpers.ps1"
#>

# Script-scoped log file path, shared across functions
$script:LogFilePath = $null

function Initialize-LogFile {
    <#
    .SYNOPSIS
    Creates or adopts a log file for the current script run.

    .PARAMETER Action
    Name used in the log filename (e.g., "install", "install-backend").

    .PARAMETER LogFilePath
    Optional. Pre-existing log path from an orchestrator.
    When provided, adopts that path instead of creating a new file.
    #>
    param(
        [Parameter(Mandatory)][string]$Action,
        [string]$LogFilePath
    )

    if ($LogFilePath -and (Test-Path $LogFilePath -PathType Leaf -ErrorAction SilentlyContinue)) {
        $script:LogFilePath = $LogFilePath
        Write-Log "--- $Action started ---"
        return
    }

    $logsDir = Join-Path (Get-Location) "logs"
    if (-not (Test-Path $logsDir)) {
        New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
    }

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $script:LogFilePath = Join-Path $logsDir "$Action-$timestamp.log"

    $header = @"
========================================
OpenPalantir $Action
Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
========================================
"@
    Set-Content -Path $script:LogFilePath -Value $header -Encoding UTF8
}

function Write-Log {
    <#
    .SYNOPSIS
    Appends a timestamped message to the log file.

    .PARAMETER Message
    The text to log.

    .PARAMETER Level
    Log level: INFO (default), WARN, or ERROR.
    #>
    param(
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet("INFO","WARN","ERROR")][string]$Level = "INFO"
    )

    if (-not $script:LogFilePath) { return }
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] [$Level] $Message" | Out-File -FilePath $script:LogFilePath -Append -Encoding UTF8
}

function Invoke-LoggedProcess {
    <#
    .SYNOPSIS
    Runs an external command, captures all output to the log file, returns exit code.

    .DESCRIPTION
    Console output is suppressed (logged only). Use -ShowOutput to also echo to console.
    Uses Start-Process with redirect for direct executables.
    Uses cmd.exe with >> redirect for batch files and shell commands (-UseCmdShell).

    .PARAMETER FilePath
    Path to the executable or command name.

    .PARAMETER ArgumentList
    Arguments to pass to the executable.

    .PARAMETER WorkingDirectory
    Working directory for the command.

    .PARAMETER UseCmdShell
    Wrap command in cmd /c with shell-level >> redirect.
    Required for .bat/.cmd files and commands like npm, tar.

    .PARAMETER ShowOutput
    If set, also echoes captured output to console via Write-Host.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [switch]$UseCmdShell,
        [switch]$ShowOutput
    )

    if (-not $script:LogFilePath) {
        if ($UseCmdShell) {
            $argStr = if ($ArgumentList) { $ArgumentList -join ' ' } else { '' }
            $cmdStr = if ($argStr) { "`"$FilePath`" $argStr" } else { "`"$FilePath`"" }
            if ($WorkingDirectory) {
                & cmd /c "cd /d `"$WorkingDirectory`" && $cmdStr"
            } else {
                & cmd /c $cmdStr
            }
            return $LASTEXITCODE
        } else {
            $sp = @{ FilePath = $FilePath; Wait = $true; NoNewWindow = $true; PassThru = $true }
            if ($ArgumentList)      { $sp.ArgumentList      = $ArgumentList }
            if ($WorkingDirectory)  { $sp.WorkingDirectory  = $WorkingDirectory }
            $process = Start-Process @sp
            return $process.ExitCode
        }
    }

    $argStr = if ($ArgumentList) { $ArgumentList -join ' ' } else { '' }
    $cmdLine = if ($argStr) { "$FilePath $argStr" } else { $FilePath }
    Write-Log "EXEC: $cmdLine"
    if ($WorkingDirectory) { Write-Log "  CWD: $WorkingDirectory" }

    if (-not $UseCmdShell) {
        # Start-Process with redirect to temp files, then append to log
        $tmpOut = "$script:LogFilePath.stdout.tmp"
        $tmpErr = "$script:LogFilePath.stderr.tmp"

        $sp = @{
            FilePath               = $FilePath
            Wait                   = $true
            NoNewWindow            = $true
            PassThru               = $true
            RedirectStandardOutput = $tmpOut
            RedirectStandardError  = $tmpErr
        }
        if ($ArgumentList)      { $sp.ArgumentList      = $ArgumentList }
        if ($WorkingDirectory)  { $sp.WorkingDirectory  = $WorkingDirectory }

        $process = Start-Process @sp

        foreach ($tmp in @($tmpOut, $tmpErr)) {
            if (Test-Path $tmp) {
                $content = Get-Content $tmp -Raw -ErrorAction SilentlyContinue
                if ($content) {
                    $content | Out-File -FilePath $script:LogFilePath -Append -Encoding UTF8
                    if ($ShowOutput) { Write-Host $content }
                }
                Remove-Item $tmp -Force -ErrorAction SilentlyContinue
            }
        }

        Write-Log "EXIT CODE: $($process.ExitCode)"
        return $process.ExitCode
    } else {
        # cmd /c with shell-level >> redirect (good for .bat/.cmd, npm, tar)
        $logEsc = $script:LogFilePath -replace '"', '""'
        $cmdStr = if ($argStr) { "`"$FilePath`" $argStr" } else { "`"$FilePath`"" }
        $shellCmd = if ($WorkingDirectory) {
            "cd /d `"$WorkingDirectory`" && $cmdStr >> `"$logEsc`" 2>&1"
        } else {
            "$cmdStr >> `"$logEsc`" 2>&1"
        }

        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "cmd.exe"
        # Use /S and wrap $shellCmd in an outer quote pair: cmd then strips ONLY the
        # outermost quotes and keeps the inner ones verbatim. Without /S, cmd's default
        # quote-stripping mangles any command with more than two quote characters (a quoted
        # exe path + a quoted ">>" redirect), turning "foo.exe" into foo.exe" and failing
        # with "The filename, directory name, or volume label syntax is incorrect."
        $psi.Arguments = "/s /c `"$shellCmd`""
        $psi.UseShellExecute = $false
        if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }

        $proc = [System.Diagnostics.Process]::Start($psi)
        $proc.WaitForExit()

        Write-Log "EXIT CODE: $($proc.ExitCode)"
        return $proc.ExitCode
    }
}
