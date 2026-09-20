param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("radar", "dashboard")]
    [string]$Service,
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,
    [ValidateSet("serial", "mock")]
    [string]$Mode = "serial",
    [string]$RadarPort = "",
    [int]$Baudrate = 115200,
    [string]$OllamaBaseUrl = "http://127.0.0.1:11434",
    [string]$OllamaModel = "qwen3:0.6b",
    [ValidateSet("enabled", "disabled")]
    [string]$AudioMode = "enabled",
    [int]$AlarmVolume = 100,
    [int]$DashboardPort = 8501
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Set-Location -LiteralPath $RepoRoot

if ($Service -eq "dashboard") {
    $Host.UI.RawUI.WindowTitle = "LD6002C AI Live Monitor"
    Write-Host "Starting AI Live Monitor at http://127.0.0.1:$DashboardPort"
    & $PythonExe -m streamlit run (Join-Path $RepoRoot "dashboard\app.py") `
        --server.address 127.0.0.1 `
        --server.port $DashboardPort `
        --server.headless true `
        --server.fileWatcherType none `
        --browser.gatherUsageStats false
    $serviceExitCode = $LASTEXITCODE
}
else {
    $Host.UI.RawUI.WindowTitle = "LD6002C Fall Detection"
    $arguments = @(
        "-m", "ld6002c_fall.main",
        "--mode", $Mode,
        "--enable-ai",
        "--ollama-base-url", $OllamaBaseUrl,
        "--ollama-model", $OllamaModel,
        "--alarm-volume", $AlarmVolume.ToString()
    )
    if ($AudioMode -eq "enabled") {
        $arguments += "--enable-audio-alarm"
    }
    else {
        $arguments += "--disable-audio-alarm"
    }
    if ($Mode -eq "serial") {
        $arguments += @("--port", $RadarPort, "--baudrate", $Baudrate.ToString())
    }
    else {
        $arguments += @(
            "--mock-scenario", "fall-demo",
            "--suspect-seconds", "1",
            "--confirm-seconds", "2"
        )
    }

    Write-Host ("Starting LD6002C in {0} mode" -f $Mode.ToUpperInvariant())
    $quotedArguments = ($arguments | ForEach-Object {
        '"' + ([string]$_).Replace('"', '\"') + '"'
    }) -join " "
    $pythonProcess = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList $quotedArguments `
        -WorkingDirectory $RepoRoot `
        -NoNewWindow `
        -PassThru
    Start-Sleep -Seconds 1
    if ($pythonProcess.HasExited) {
        $serviceExitCode = $pythonProcess.ExitCode
    }
    else {
        $readyPath = Join-Path $RepoRoot "data\windows-runtime\radar.ready"
        Set-Content -LiteralPath $readyPath -Value $pythonProcess.Id -Encoding ASCII
        $pythonProcess.WaitForExit()
        $serviceExitCode = $pythonProcess.ExitCode
        Remove-Item -LiteralPath $readyPath -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host ("Service stopped with exit code {0}." -f $serviceExitCode) -ForegroundColor Yellow
