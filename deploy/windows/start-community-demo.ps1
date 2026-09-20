param(
    [switch]$Reset
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "common.ps1")
Initialize-Utf8Console

$repoRoot = Get-ProjectRoot
$pythonExe = Get-PythonExecutable $repoRoot
$ollamaProcess = $null
$ollamaStartedByScript = $false

try {
    Set-Location -LiteralPath $repoRoot
    $dashboardPort = if ([string]::IsNullOrWhiteSpace($env:LD6002C_DASHBOARD_PORT)) { 8501 } else { [int]$env:LD6002C_DASHBOARD_PORT }
    $ollamaBaseUrl = if ([string]::IsNullOrWhiteSpace($env:OLLAMA_BASE_URL)) { "http://127.0.0.1:11434" } else { $env:OLLAMA_BASE_URL.TrimEnd('/') }
    $ollamaModel = if ([string]::IsNullOrWhiteSpace($env:OLLAMA_MODEL)) { "qwen3:0.6b" } else { $env:OLLAMA_MODEL }
    $alarmVolume = if ([string]::IsNullOrWhiteSpace($env:ALARM_VOLUME)) { 100 } else { [int]$env:ALARM_VOLUME }

    Write-Step 1 3 "Checking offline Python environment..."
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw "Project .venv is missing. Run INSTALL_WINDOWS_OFFLINE.bat first."
    }
    & $pythonExe -c "import struct,sys; assert sys.version_info[:2] == (3, 14) and struct.calcsize('P') * 8 == 64; import ld6002c_fall, streamlit"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.14 x64 or the offline project dependencies are incomplete. Run INSTALL_WINDOWS_OFFLINE.bat."
    }
    Write-Ok "Python 3.14 x64 and project dependencies"

    if ($Reset) {
        & $pythonExe -m ld6002c_fall.community_demo --reset
        exit $LASTEXITCODE
    }

    Write-Step 2 3 "Checking local Ollama and qwen3:0.6b..."
    $tags = Get-OllamaTags $ollamaBaseUrl
    if ($null -eq $tags) {
        $ollamaExe = Get-OllamaExecutable $repoRoot
        if ([string]::IsNullOrWhiteSpace($ollamaExe)) {
            throw "Ollama is offline and ollama.exe was not found. Install Ollama or restore runtime\ollama."
        }
        if ($ollamaBaseUrl -notin @("http://127.0.0.1:11434", "http://localhost:11434")) {
            throw "Automatic Ollama startup is limited to localhost."
        }
        $ollamaProcess = Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Minimized -PassThru
        $ollamaStartedByScript = $true
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            Start-Sleep -Seconds 1
            $tags = Get-OllamaTags $ollamaBaseUrl
            if ($null -ne $tags) { break }
        }
    }
    if ($null -eq $tags) {
        throw "Ollama did not become ready within 20 seconds."
    }
    $modelNames = @(Get-OllamaModelNames $tags)
    if ($modelNames -notcontains $ollamaModel) {
        throw "AI model $ollamaModel is missing. Run INSTALL_WINDOWS_OFFLINE.bat; no download was attempted."
    }
    Write-Ok "Ollama and model $ollamaModel"

    $ffplayExe = Get-FfplayExecutable $repoRoot
    $audioArgs = @("--audio-alarm")
    if ([string]::IsNullOrWhiteSpace($ffplayExe)) {
        Write-Warn "ffplay.exe not found; the demo will use console alarm output."
        $audioArgs = @("--no-audio-alarm")
    }
    else {
        $env:PATH = (Split-Path -Parent $ffplayExe) + ";" + $env:PATH
    }

    Write-Step 3 3 "Starting the community dashboard and mobile control page..."
    $arguments = @(
        "-m", "ld6002c_fall.community_demo",
        "--host", "0.0.0.0",
        "--port", $dashboardPort.ToString(),
        "--enable-ai",
        "--ollama-base-url", $ollamaBaseUrl,
        "--ollama-model", $ollamaModel,
        "--alarm-volume", $alarmVolume.ToString(),
        "--open-browser"
    ) + $audioArgs
    & $pythonExe @arguments
    exit $LASTEXITCODE
}
catch {
    Write-Host ""
    Write-Host ("[ERROR] {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}
finally {
    if ($ollamaStartedByScript -and $null -ne $ollamaProcess) {
        Stop-Process -Id $ollamaProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
