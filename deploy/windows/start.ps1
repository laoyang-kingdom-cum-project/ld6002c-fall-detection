$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "common.ps1")
Initialize-Utf8Console

$repoRoot = Get-ProjectRoot
$pythonExe = Get-PythonExecutable $repoRoot
$runtimeDirectory = Get-RuntimeDirectory $repoRoot
$radarPidPath = Join-Path $runtimeDirectory "radar.pid"
$radarReadyPath = Join-Path $runtimeDirectory "radar.ready"
$dashboardPidPath = Join-Path $runtimeDirectory "dashboard.pid"
$ollamaPidPath = Join-Path $runtimeDirectory "ollama.pid"
$ollamaPathState = Join-Path $runtimeDirectory "ollama.path"
$runnerPath = Join-Path $PSScriptRoot "run-service.ps1"
$radarProcess = $null
$dashboardProcess = $null
$ollamaProcess = $null
$ollamaStartedByScript = $false

function Get-IntegerSetting {
    param(
        [string]$Name,
        [int]$Default,
        [int]$Minimum,
        [int]$Maximum
    )
    $raw = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $Default
    }
    $parsed = 0
    if (-not [int]::TryParse($raw, [ref]$parsed) -or $parsed -lt $Minimum -or $parsed -gt $Maximum) {
        throw ("Invalid {0}: {1}. Expected {2}-{3}." -f $Name, $raw, $Minimum, $Maximum)
    }
    return $parsed
}

function Get-PortInventory {
    $detector = Join-Path $repoRoot "tools\detect_ld6002c_port.py"
    $json = & $pythonExe $detector --json
    if ($LASTEXITCODE -ne 0) {
        throw "Serial port detection failed."
    }
    if ([string]::IsNullOrWhiteSpace(($json -join ""))) {
        return @()
    }
    return @($json | ConvertFrom-Json)
}

function Show-PortInventory {
    param([object[]]$Ports)
    for ($index = 0; $index -lt $Ports.Count; $index++) {
        $description = [string]$Ports[$index].description
        if ([string]::IsNullOrWhiteSpace($description)) {
            $description = "Unknown serial device"
        }
        $candidate = if ($Ports[$index].is_ld6002c_candidate) { " [CP210x candidate]" } else { "" }
        Write-Host ("      [{0}] {1} - {2}{3}" -f ($index + 1), $Ports[$index].device, $description, $candidate)
    }
}

function Test-RadarPort {
    param(
        [string]$Port,
        [int]$Baudrate
    )
    $detector = Join-Path $repoRoot "tools\detect_ld6002c_port.py"
    $json = & $pythonExe $detector --probe $Port --baudrate $Baudrate
    $exitCode = $LASTEXITCODE
    try {
        $result = $json | ConvertFrom-Json
    }
    catch {
        return [PSCustomObject]@{ ok = $false; message = "Port probe returned invalid output." }
    }
    if ($exitCode -ne 0) {
        return [PSCustomObject]@{ ok = $false; message = [string]$result.message }
    }
    return $result
}

function Stop-StartedProcessTree {
    param([object]$ProcessObject)
    if ($null -eq $ProcessObject) {
        return
    }
    $processId = [int]$ProcessObject.Id
    $existing = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
    }
}

try {
    Set-Location -LiteralPath $repoRoot
    $dashboardPort = Get-IntegerSetting "LD6002C_DASHBOARD_PORT" 8501 1 65535
    $baudrate = Get-IntegerSetting "LD6002C_BAUDRATE" 115200 1 4000000
    $alarmVolume = Get-IntegerSetting "ALARM_VOLUME" 100 0 100
    $ollamaBaseUrl = if ([string]::IsNullOrWhiteSpace($env:OLLAMA_BASE_URL)) { "http://127.0.0.1:11434" } else { $env:OLLAMA_BASE_URL.TrimEnd('/') }
    $ollamaModel = if ([string]::IsNullOrWhiteSpace($env:OLLAMA_MODEL)) { "qwen3:0.6b" } else { $env:OLLAMA_MODEL }
    $dashboardUrl = "http://127.0.0.1:$dashboardPort"

    $existingRadar = Get-ManagedProjectProcess $radarPidPath $repoRoot
    $existingDashboard = Get-ManagedProjectProcess $dashboardPidPath $repoRoot
    if ($null -eq $existingRadar) { Remove-StalePidFile $radarPidPath }
    if ($null -eq $existingDashboard) { Remove-StalePidFile $dashboardPidPath }
    if (
        $null -ne $existingRadar -and
        $null -ne $existingDashboard -and
        (Test-Path -LiteralPath $radarReadyPath -PathType Leaf) -and
        (Test-HttpEndpoint $dashboardUrl)
    ) {
        Write-Host "LD6002C Fall Detection is already running." -ForegroundColor Yellow
        Write-Host "Dashboard: $dashboardUrl"
        Start-Process $dashboardUrl
        exit 0
    }
    if ($null -ne $existingRadar -or $null -ne $existingDashboard) {
        throw "An incomplete project runtime is still active. Run STOP_WINDOWS.bat, then start again."
    }

    Write-Step 1 6 "Checking Python runtime..."
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw ("Project virtual environment is missing: {0}`nRun the Windows offline installation process first." -f $pythonExe)
    }
    & $pythonExe -c "import sys; assert sys.version_info >= (3, 11); import ld6002c_fall, serial, streamlit"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11+, the project package, pyserial, or Streamlit is not ready in .venv."
    }
    $pythonVersion = (& $pythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    Write-Ok "Python $pythonVersion and project package"

    Write-Step 2 6 "Checking Ollama service..."
    $tags = Get-OllamaTags $ollamaBaseUrl
    if ($null -eq $tags) {
        $ollamaExe = Get-OllamaExecutable $repoRoot
        if ([string]::IsNullOrWhiteSpace($ollamaExe)) {
            throw "Ollama service is offline and ollama.exe was not found in PATH, LocalAppData, or runtime\ollama."
        }
        if ($ollamaBaseUrl -ne "http://127.0.0.1:11434" -and $ollamaBaseUrl -ne "http://localhost:11434") {
            throw "The configured OLLAMA_BASE_URL is offline. Automatic startup is limited to the local default endpoint."
        }
        Write-Warn "Ollama is offline; starting local ollama serve"
        $ollamaProcess = Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Minimized -PassThru
        $ollamaStartedByScript = $true
        Set-Content -LiteralPath $ollamaPidPath -Value $ollamaProcess.Id -Encoding ASCII
        Set-Content -LiteralPath $ollamaPathState -Value ([IO.Path]::GetFullPath($ollamaExe)) -Encoding UTF8
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            Start-Sleep -Seconds 1
            $tags = Get-OllamaTags $ollamaBaseUrl
            if ($null -ne $tags) { break }
        }
        if ($null -eq $tags) {
            throw "Ollama service failed to start within 20 seconds."
        }
    }
    Write-Ok "Ollama service ONLINE"

    Write-Step 3 6 "Checking AI model..."
    $modelNames = @(Get-OllamaModelNames $tags)
    if ($modelNames -notcontains $ollamaModel) {
        throw ("AI model missing: {0}`nPrepare the model on a connected computer and copy the Ollama model store before the lesson. No download was attempted." -f $ollamaModel)
    }
    Write-Ok "AI model $ollamaModel"

    Write-Step 4 6 "Detecting LD6002C serial port..."
    $mode = "serial"
    $radarPort = ""
    $manualPort = $env:LD6002C_PORT
    while ([string]::IsNullOrWhiteSpace($radarPort) -and $mode -eq "serial") {
        if (-not [string]::IsNullOrWhiteSpace($manualPort)) {
            $radarPort = $manualPort.Trim()
            Write-Host ("      Radar Port: {0} (manual override)" -f $radarPort)
        }
        else {
            $ports = @(Get-PortInventory)
            $candidates = @($ports | Where-Object { $_.is_ld6002c_candidate })
            if ($candidates.Count -eq 1) {
                $radarPort = [string]$candidates[0].device
                Write-Host ("      {0} - {1}" -f $radarPort, $candidates[0].description)
            }
            elseif ($candidates.Count -gt 1) {
                Write-Warn "Multiple possible serial devices were found."
                Show-PortInventory $ports
                $choice = (Read-Host ("Select the LD6002C port [1-{0}], M=mock, R=rescan, Q=quit" -f $ports.Count)).Trim()
                if ($choice -match '^[mM]$') { $mode = "mock"; break }
                if ($choice -match '^[qQ]$') { throw "Startup cancelled by user." }
                if ($choice -match '^[rR]$') { continue }
                $selection = 0
                if ([int]::TryParse($choice, [ref]$selection) -and $selection -ge 1 -and $selection -le $ports.Count) {
                    $radarPort = [string]$ports[$selection - 1].device
                }
                else {
                    Write-Warn "Invalid selection."
                    continue
                }
            }
            else {
                if ($ports.Count -gt 0) {
                    Write-Warn "Serial ports were found, but none has clear CP210x metadata."
                    Show-PortInventory $ports
                }
                else {
                    Write-Warn "No serial ports were found."
                }
                $choice = (Read-Host "M=Mock Fall Demo, R=rescan, Q=quit").Trim()
                if ($choice -match '^[mM]$') { $mode = "mock"; break }
                if ($choice -match '^[qQ]$') { throw "Startup cancelled by user." }
                continue
            }
        }

        if (-not [string]::IsNullOrWhiteSpace($radarPort)) {
            $probe = Test-RadarPort $radarPort $baudrate
            if (-not $probe.ok) {
                Write-Host ("      [ERROR] {0} cannot be opened: {1}" -f $radarPort, $probe.message) -ForegroundColor Red
                Write-Host "      Close the vendor radar tool, serial terminal, or another ld6002c-fall process."
                $radarPort = ""
                $choice = (Read-Host "R=retry/rescan, M=Mock Fall Demo, Q=quit").Trim()
                if ($choice -match '^[mM]$') { $mode = "mock"; break }
                if ($choice -match '^[qQ]$') { throw "Startup cancelled by user." }
                continue
            }
        }
    }
    if ($mode -eq "mock") {
        Write-Warn "Mode: MOCK FALL DEMO - data is simulated, not a real LD6002C."
    }
    else {
        Write-Ok "LD6002C port $radarPort is available"
    }

    $ffplayExe = Get-FfplayExecutable $repoRoot
    $audioEnabled = $true
    if ([string]::IsNullOrWhiteSpace($ffplayExe)) {
        $audioEnabled = $false
        Write-Warn "ffplay.exe not found; audio alarm will be disabled."
    }
    else {
        $ffplayDirectory = Split-Path -Parent $ffplayExe
        $env:PATH = $ffplayDirectory + ";" + $env:PATH
        Write-Ok "Audio alarm ready"
    }

    if (Test-TcpPort -Port $dashboardPort) {
        throw ("Dashboard port {0} is already in use by an unmanaged process. Set LD6002C_DASHBOARD_PORT or close that process." -f $dashboardPort)
    }

    Write-Step 5 6 "Starting radar service..."
    Remove-StalePidFile $radarReadyPath
    $radarProcess = Start-ProjectWindow `
        -RunnerPath $runnerPath `
        -Service "radar" `
        -RepoRoot $repoRoot `
        -PythonExe $pythonExe `
        -Mode $mode `
        -RadarPort $radarPort `
        -Baudrate $baudrate `
        -OllamaBaseUrl $ollamaBaseUrl `
        -OllamaModel $ollamaModel `
        -AudioEnabled $audioEnabled `
        -AlarmVolume $alarmVolume `
        -DashboardPort $dashboardPort
    Set-Content -LiteralPath $radarPidPath -Value $radarProcess.Id -Encoding ASCII
    $radarReady = $false
    for ($attempt = 0; $attempt -lt 8; $attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-Path -LiteralPath $radarReadyPath -PathType Leaf) {
            $radarReady = $true
            break
        }
        if ($null -eq (Get-Process -Id $radarProcess.Id -ErrorAction SilentlyContinue)) {
            break
        }
    }
    if (-not $radarReady) {
        throw "Radar service exited during startup. Review its console window."
    }
    Write-Ok "Radar service window started"

    Write-Step 6 6 "Starting AI Live Monitor..."
    $dashboardProcess = Start-ProjectWindow `
        -RunnerPath $runnerPath `
        -Service "dashboard" `
        -RepoRoot $repoRoot `
        -PythonExe $pythonExe `
        -Mode $mode `
        -RadarPort $radarPort `
        -Baudrate $baudrate `
        -OllamaBaseUrl $ollamaBaseUrl `
        -OllamaModel $ollamaModel `
        -AudioEnabled $audioEnabled `
        -AlarmVolume $alarmVolume `
        -DashboardPort $dashboardPort
    Set-Content -LiteralPath $dashboardPidPath -Value $dashboardProcess.Id -Encoding ASCII
    $dashboardReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-HttpEndpoint $dashboardUrl) {
            $dashboardReady = $true
            break
        }
    }
    if (-not $dashboardReady) {
        throw "AI Live Monitor did not become reachable within 30 seconds. Check its console window."
    }
    Start-Process $dashboardUrl

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host " LD6002C AI Fall Detection Ready" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host ("Radar     : {0}" -f $(if ($mode -eq "serial") { $radarPort } else { "SIMULATED" }))
    Write-Host "Ollama    : ONLINE"
    Write-Host ("Model     : {0}" -f $ollamaModel)
    Write-Host ("Dashboard : {0}" -f $dashboardUrl)
    Write-Host ("Mode      : {0}" -f $(if ($mode -eq "serial") { "SERIAL" } else { "MOCK FALL DEMO" }))
    Write-Host ("Audio     : {0}" -f $(if ($audioEnabled) { "ENABLED" } else { "DISABLED" }))
    Write-Host ""
    Write-Host "Use STOP_WINDOWS.bat to stop only this project."
    exit 0
}
catch {
    Write-Host ""
    Write-Host ("[ERROR] {0}" -f $_.Exception.Message) -ForegroundColor Red
    Stop-StartedProcessTree $dashboardProcess
    Stop-StartedProcessTree $radarProcess
    Remove-StalePidFile $dashboardPidPath
    Remove-StalePidFile $radarPidPath
    Remove-StalePidFile $radarReadyPath
    if ($ollamaStartedByScript -and $null -ne $ollamaProcess) {
        Stop-Process -Id $ollamaProcess.Id -Force -ErrorAction SilentlyContinue
        Remove-StalePidFile $ollamaPidPath
        Remove-StalePidFile $ollamaPathState
    }
    exit 1
}
