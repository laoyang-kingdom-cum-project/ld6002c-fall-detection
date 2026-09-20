$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "common.ps1")
Initialize-Utf8Console

$repoRoot = Get-ProjectRoot
$pythonExe = Get-PythonExecutable $repoRoot
$runtimeDirectory = Get-RuntimeDirectory $repoRoot
$dashboardPidPath = Join-Path $runtimeDirectory "dashboard.pid"
$ollamaBaseUrl = if ([string]::IsNullOrWhiteSpace($env:OLLAMA_BASE_URL)) { "http://127.0.0.1:11434" } else { $env:OLLAMA_BASE_URL.TrimEnd('/') }
$ollamaModel = if ([string]::IsNullOrWhiteSpace($env:OLLAMA_MODEL)) { "qwen3:0.6b" } else { $env:OLLAMA_MODEL }
$dashboardPort = 8501
$dashboardPortConfigError = $false
if (-not [string]::IsNullOrWhiteSpace($env:LD6002C_DASHBOARD_PORT)) {
    $parsedPort = 0
    if (
        [int]::TryParse($env:LD6002C_DASHBOARD_PORT, [ref]$parsedPort) -and
        $parsedPort -ge 1 -and
        $parsedPort -le 65535
    ) {
        $dashboardPort = $parsedPort
    }
    else {
        $dashboardPortConfigError = $true
    }
}
$script:errorCount = 0
$script:warningCount = 0

function Report-Ok {
    param([string]$Message)
    Write-Host ("[OK]    {0}" -f $Message) -ForegroundColor Green
}

function Report-Warn {
    param([string]$Message)
    $script:warningCount++
    Write-Host ("[WARN]  {0}" -f $Message) -ForegroundColor Yellow
}

function Report-Error {
    param([string]$Message)
    $script:errorCount++
    Write-Host ("[ERROR] {0}" -f $Message) -ForegroundColor Red
}

Write-Host "Windows Offline Environment Check" -ForegroundColor Cyan
Write-Host ""

try {
    $windows = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    Report-Ok ("Windows {0} ({1})" -f $windows.Version, $windows.OSArchitecture)
}
catch {
    Report-Error "Unable to read the Windows version."
}
Report-Ok ("Repo path: {0}" -f $repoRoot)
if ($dashboardPortConfigError) {
    Report-Error ("Invalid LD6002C_DASHBOARD_PORT: {0}. Expected 1-65535." -f $env:LD6002C_DASHBOARD_PORT)
}

if (Test-Path -LiteralPath $pythonExe -PathType Leaf) {
    $versionOutput = & $pythonExe -c "import struct,sys; print('.'.join(map(str, sys.version_info[:3])) + ' x' + str(struct.calcsize('P') * 8))" 2>$null
    $versionExitCode = $LASTEXITCODE
    $version = ($versionOutput -join "").Trim()
    if ($versionExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($version)) {
        Report-Ok ("Python venv: {0}" -f $version)
    }
    else {
        Report-Error "The project Python executable cannot run."
    }
    & $pythonExe -c "import struct,sys; assert sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64; import ld6002c_fall, serial, streamlit" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Report-Ok "Project package, pyserial, and Streamlit"
    }
    else {
        Report-Error "Project import failed or .venv is not Python 3.11 x64."
    }
}
else {
    Report-Error ("Python venv missing: {0}" -f $pythonExe)
}

$ollamaExe = Get-OllamaExecutable $repoRoot
if ([string]::IsNullOrWhiteSpace($ollamaExe)) {
    Report-Error "Ollama is not installed in PATH, LocalAppData, or runtime\ollama."
}
else {
    Report-Ok ("Ollama executable: {0}" -f $ollamaExe)
}

$tags = Get-OllamaTags $ollamaBaseUrl
if ($null -eq $tags) {
    if (-not [string]::IsNullOrWhiteSpace($ollamaExe)) {
        Report-Warn "Ollama service is currently stopped. START_WINDOWS.bat will start it automatically."
        Report-Warn ("AI model cannot be verified through the API until Ollama starts: {0}" -f $ollamaModel)
    }
    $targetModelStore = Get-OllamaModelStore
    $targetModelStatus = Get-OllamaModelFileStatus -ModelStore $targetModelStore -ModelName $ollamaModel
    if ($targetModelStatus.Complete) {
        Report-Ok ("Offline model store: {0}" -f $ollamaModel)
    }
    else {
        $sourceModelStore = Join-Path $repoRoot "models"
        $sourceModelStatus = Get-OllamaModelFileStatus -ModelStore $sourceModelStore -ModelName $ollamaModel
        if ($sourceModelStatus.Complete) {
            Report-Warn ("Packaged offline model is available but is not installed. Run INSTALL_WINDOWS_OFFLINE.bat: {0}" -f $ollamaModel)
        }
        else {
            Report-Error ("Offline model is missing or incomplete in both the Ollama store and repo models directory: {0}" -f $ollamaModel)
        }
    }
}
else {
    Report-Ok ("Ollama API: {0}" -f $ollamaBaseUrl)
    $names = @(Get-OllamaModelNames $tags)
    if ($names -contains $ollamaModel) {
        Report-Ok ("AI model: {0}" -f $ollamaModel)
    }
    else {
        Report-Error ("AI model missing: {0}" -f $ollamaModel)
    }
}

if (Test-Path -LiteralPath $pythonExe -PathType Leaf) {
    $detector = Join-Path $repoRoot "tools\detect_ld6002c_port.py"
    try {
        if (-not [string]::IsNullOrWhiteSpace($env:LD6002C_PORT)) {
            $manualPort = $env:LD6002C_PORT.Trim()
            $probeJson = & $pythonExe $detector --probe $manualPort
            $probeExitCode = $LASTEXITCODE
            $probe = $probeJson | ConvertFrom-Json
            if ($probeExitCode -eq 0 -and $probe.ok) {
                Report-Ok ("LD6002C manual port: {0}" -f $manualPort)
            }
            else {
                Report-Error ("LD6002C manual port cannot be opened: {0} - {1}" -f $manualPort, $probe.message)
            }
        }
        else {
            $json = & $pythonExe $detector --json
            $ports = @($json | ConvertFrom-Json)
            $candidates = @($ports | Where-Object { $_.is_ld6002c_candidate })
            if ($candidates.Count -eq 1) {
                Report-Ok ("LD6002C candidate: {0} - {1}" -f $candidates[0].device, $candidates[0].description)
            }
            elseif ($candidates.Count -gt 1) {
                Report-Warn ("Multiple CP210x candidates found: {0}" -f (($candidates | ForEach-Object { $_.device }) -join ", "))
            }
            elseif ($ports.Count -gt 0) {
                Report-Warn ("Serial ports found, but no clear CP210x candidate: {0}" -f (($ports | ForEach-Object { $_.device }) -join ", "))
            }
            else {
                Report-Warn "No serial ports found; START_WINDOWS.bat can use Mock Fall Demo."
            }
        }
    }
    catch {
        Report-Error ("Serial port scan failed: {0}" -f $_.Exception.Message)
    }
}

$ffplayExe = Get-FfplayExecutable $repoRoot
if ([string]::IsNullOrWhiteSpace($ffplayExe)) {
    Report-Warn "ffplay.exe not found; startup will disable audio alarm."
}
else {
    Report-Ok ("ffplay: {0}" -f $ffplayExe)
}

$dashboardPath = Join-Path $repoRoot "dashboard\app.py"
if (Test-Path -LiteralPath $dashboardPath -PathType Leaf) {
    Report-Ok "Dashboard application"
}
else {
    Report-Error ("Dashboard missing: {0}" -f $dashboardPath)
}

$soundPath = Join-Path $repoRoot "studio_video_1778294323944.mp3"
if (Test-Path -LiteralPath $soundPath -PathType Leaf) {
    Report-Ok "Alarm sound file"
}
else {
    Report-Warn "Alarm sound file missing; console alarm remains available."
}

$dataDirectory = Join-Path $repoRoot "data"
try {
    if (-not (Test-Path -LiteralPath $dataDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
    }
    $writeTest = Join-Path $dataDirectory ("windows-write-test-{0}.tmp" -f [Guid]::NewGuid().ToString("N"))
    Set-Content -LiteralPath $writeTest -Value "ok" -Encoding ASCII
    Remove-Item -LiteralPath $writeTest -Force
    Report-Ok "data directory writable"
}
catch {
    Report-Error ("data directory is not writable: {0}" -f $_.Exception.Message)
}

if (Test-TcpPort -Port $dashboardPort) {
    $managedDashboard = Get-ManagedProjectProcess $dashboardPidPath $repoRoot
    if ($null -ne $managedDashboard -and (Test-HttpEndpoint ("http://127.0.0.1:{0}" -f $dashboardPort))) {
        Report-Ok ("Dashboard already running on port {0}" -f $dashboardPort)
    }
    else {
        Report-Error ("Dashboard port {0} is occupied by another process." -f $dashboardPort)
    }
}
else {
    Report-Ok ("Dashboard port {0} available" -f $dashboardPort)
}

try {
    $ollamaUri = [Uri]$ollamaBaseUrl
    $ollamaHost = $ollamaUri.Host
    $ollamaPort = $ollamaUri.Port
    if ($null -ne $tags) {
        Report-Ok ("Ollama endpoint {0}:{1} is serving the tags API" -f $ollamaHost, $ollamaPort)
    }
    elseif (Test-TcpPort -HostName $ollamaHost -Port $ollamaPort) {
        Report-Error ("Ollama endpoint {0}:{1} accepts TCP connections, but the tags API did not respond." -f $ollamaHost, $ollamaPort)
    }
    elseif ($ollamaHost -eq "127.0.0.1" -or $ollamaHost -eq "localhost") {
        Report-Warn ("Ollama port {0} is free; START_WINDOWS.bat will try to start the local service." -f $ollamaPort)
    }
    else {
        Report-Warn ("Configured Ollama endpoint is unreachable: {0}" -f $ollamaBaseUrl)
    }
}
catch {
    Report-Error ("Invalid OLLAMA_BASE_URL: {0}" -f $ollamaBaseUrl)
}

Write-Host ""
if ($script:errorCount -eq 0) {
    Write-Host "READY FOR DEMO" -ForegroundColor Green
    if ($script:warningCount -gt 0) {
        Write-Host ("Optional warnings: {0}" -f $script:warningCount) -ForegroundColor Yellow
    }
    exit 0
}

Write-Host ("NOT READY - fix {0} error(s) above." -f $script:errorCount) -ForegroundColor Red
exit 1
