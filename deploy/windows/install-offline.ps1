param(
    [switch]$Repair
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "common.ps1")
Initialize-Utf8Console

$repoRoot = Get-ProjectRoot
$venvDirectory = Join-Path $repoRoot ".venv"
$venvPython = Get-PythonExecutable $repoRoot
$wheelhouse = Join-Path $repoRoot "wheelhouse"
$projectWheelDirectory = Join-Path $repoRoot "project-wheel"
$sourceModelStore = Join-Path $repoRoot "models"
$ollamaBaseUrl = if ([string]::IsNullOrWhiteSpace($env:OLLAMA_BASE_URL)) { "http://127.0.0.1:11434" } else { $env:OLLAMA_BASE_URL.TrimEnd('/') }
$ollamaModel = if ([string]::IsNullOrWhiteSpace($env:OLLAMA_MODEL)) { "qwen3:0.6b" } else { $env:OLLAMA_MODEL.Trim() }
$temporaryOllama = $null
$venvCreatedThisRun = $false

function Invoke-PythonProbe {
    param(
        [string]$FilePath,
        [string[]]$PrefixArguments = @()
    )
    $code = "import json,struct,sys; print(json.dumps({'major':sys.version_info[0],'minor':sys.version_info[1],'micro':sys.version_info[2],'bits':struct.calcsize('P')*8,'executable':sys.executable}))"
    $arguments = @($PrefixArguments) + @("-c", $code)
    $output = & $FilePath @arguments 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($output -join ""))) {
        return $null
    }
    try {
        $info = $output | Select-Object -Last 1 | ConvertFrom-Json
    }
    catch {
        return $null
    }
    return [PSCustomObject]@{
        FilePath = $FilePath
        PrefixArguments = @($PrefixArguments)
        Info = $info
    }
}

function Get-Python311Runtime {
    $pyCommand = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $pyCommand) {
        $probe = Invoke-PythonProbe -FilePath $pyCommand.Source -PrefixArguments @("-3.11")
        if ($null -ne $probe -and $probe.Info.major -eq 3 -and $probe.Info.minor -eq 11 -and $probe.Info.bits -eq 64) {
            return $probe
        }
    }

    $pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        $probe = Invoke-PythonProbe -FilePath $pythonCommand.Source
        if ($null -ne $probe -and $probe.Info.major -eq 3 -and $probe.Info.minor -eq 11 -and $probe.Info.bits -eq 64) {
            return $probe
        }
    }
    return $null
}

function Invoke-BasePython {
    param(
        [object]$Runtime,
        [string[]]$Arguments
    )
    $allArguments = @($Runtime.PrefixArguments) + @($Arguments)
    $output = & $Runtime.FilePath @allArguments 2>&1
    $exitCode = $LASTEXITCODE
    foreach ($line in @($output)) {
        Write-Host $line
    }
    return $exitCode
}

function Test-VenvPython {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        return $false
    }
    & $venvPython -c "import struct,sys; assert sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Stop-TemporaryOllama {
    if ($null -eq $script:temporaryOllama) {
        return
    }
    $process = Get-Process -Id $script:temporaryOllama.Id -ErrorAction SilentlyContinue
    if ($null -ne $process -and $process.ProcessName.StartsWith("ollama", [StringComparison]::OrdinalIgnoreCase)) {
        & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
        Write-Host "[INFO] Temporary Ollama service stopped."
    }
    $script:temporaryOllama = $null
}

function Merge-ModelStore {
    param(
        [string]$Source,
        [string]$Target
    )
    if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
        New-Item -ItemType Directory -Path $Target -Force | Out-Null
    }
    & robocopy.exe $Source $Target /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NP
    $copyExitCode = $LASTEXITCODE
    if ($copyExitCode -ge 8) {
        throw ("Offline model copy failed with robocopy exit code {0}." -f $copyExitCode)
    }
}

try {
    Set-Location -LiteralPath $repoRoot
    try {
        $ollamaUri = [Uri]$ollamaBaseUrl
    }
    catch {
        throw ("Invalid OLLAMA_BASE_URL: {0}" -f $ollamaBaseUrl)
    }
    if (
        -not $ollamaUri.IsAbsoluteUri -or
        ($ollamaUri.Host -ne "127.0.0.1" -and $ollamaUri.Host -ne "localhost" -and $ollamaUri.Host -ne "::1")
    ) {
        throw "Offline installation only supports a local Ollama endpoint."
    }
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host " LD6002C Windows Offline Installation" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    Write-Step 1 7 "Checking Python 3.11 x64..."
    $pythonRuntime = Get-Python311Runtime
    if ($null -eq $pythonRuntime) {
        throw "Python 3.11 x64 is required. Install it before running this offline installer."
    }
    Write-Ok ("Python {0}.{1}.{2} x64: {3}" -f $pythonRuntime.Info.major, $pythonRuntime.Info.minor, $pythonRuntime.Info.micro, $pythonRuntime.Info.executable)

    Write-Step 2 7 "Preparing the project virtual environment..."
    if ($Repair -and (Test-Path -LiteralPath $venvDirectory)) {
        Write-Warn "Repair requested; removing the existing project .venv"
        Remove-Item -LiteralPath $venvDirectory -Recurse -Force
    }
    if ((Test-Path -LiteralPath $venvDirectory) -and -not (Test-Path -LiteralPath $venvDirectory -PathType Container)) {
        throw "The .venv path is not a directory. Remove it or run INSTALL_WINDOWS_OFFLINE.bat -Repair."
    }
    if (Test-Path -LiteralPath $venvDirectory -PathType Container) {
        if (-not (Test-VenvPython)) {
            throw "The existing .venv is damaged or is not Python 3.11 x64. Run INSTALL_WINDOWS_OFFLINE.bat -Repair."
        }
        Write-Ok "Existing Python 3.11 x64 virtual environment"
    }
    else {
        $exitCode = Invoke-BasePython -Runtime $pythonRuntime -Arguments @("-m", "venv", $venvDirectory)
        if ($exitCode -ne 0 -or -not (Test-VenvPython)) {
            if (Test-Path -LiteralPath $venvDirectory) {
                Remove-Item -LiteralPath $venvDirectory -Recurse -Force -ErrorAction SilentlyContinue
            }
            throw "Failed to create the project .venv with Python 3.11 x64."
        }
        $venvCreatedThisRun = $true
        Write-Ok "Virtual environment created"
    }

    Write-Step 3 7 "Installing Python packages from the offline wheel directories..."
    if (-not (Test-Path -LiteralPath $wheelhouse -PathType Container)) {
        throw ("Offline wheelhouse is missing: {0}" -f $wheelhouse)
    }
    $dependencyWheels = @(Get-ChildItem -LiteralPath $wheelhouse -Filter "*.whl" -File)
    if ($dependencyWheels.Count -eq 0) {
        throw ("Offline wheelhouse contains no .whl files: {0}" -f $wheelhouse)
    }
    if (-not (Test-Path -LiteralPath $projectWheelDirectory -PathType Container)) {
        throw ("Project wheel directory is missing: {0}" -f $projectWheelDirectory)
    }
    $projectWheels = @(
        Get-ChildItem -LiteralPath $projectWheelDirectory -Filter "ld6002c_fall_detection-*.whl" -File |
            Sort-Object LastWriteTimeUtc, Name -Descending
    )
    if ($projectWheels.Count -eq 0) {
        throw ("No ld6002c_fall_detection project wheel was found in {0}" -f $projectWheelDirectory)
    }
    $projectWheel = $projectWheels[0]
    Write-Host ("      Project wheel: {0}" -f $projectWheel.Name)
    & $venvPython -m pip install --disable-pip-version-check --no-index --only-binary=:all: --find-links $wheelhouse $projectWheel.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "Offline Python package installation failed. Check that wheelhouse contains every Windows CPython 3.11 dependency."
    }
    Write-Ok "Python dependencies and project package"

    Write-Step 4 7 "Validating the Python installation..."
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "pip check reported a broken or conflicting Python dependency."
    }
    & $venvPython -c "import ld6002c_fall, serial, streamlit; print('OK')"
    if ($LASTEXITCODE -ne 0) {
        throw "Project import validation failed after offline installation."
    }
    Write-Ok "pip check and project imports"

    Write-Step 5 7 "Checking Ollama and the packaged model..."
    $ollamaExe = Get-OllamaExecutable $repoRoot
    if ([string]::IsNullOrWhiteSpace($ollamaExe)) {
        throw "Ollama is not installed. Install Ollama Windows before running this installer."
    }
    Write-Ok ("Ollama: {0}" -f $ollamaExe)
    $sourceStatus = Get-OllamaModelFileStatus -ModelStore $sourceModelStore -ModelName $ollamaModel
    if (-not $sourceStatus.Complete) {
        throw ("Packaged offline model is incomplete: {0} ({1})" -f $ollamaModel, $sourceStatus.Reason)
    }
    Write-Ok ("Packaged model {0}" -f $ollamaModel)

    Write-Step 6 7 "Installing the offline Ollama model..."
    $targetModelStore = Get-OllamaModelStore
    if ([string]::IsNullOrWhiteSpace($targetModelStore)) {
        throw "Cannot determine the Ollama model store. Set OLLAMA_MODELS or USERPROFILE."
    }
    $targetStatus = Get-OllamaModelFileStatus -ModelStore $targetModelStore -ModelName $ollamaModel
    if ($targetStatus.Complete) {
        Write-Ok ("Offline model already installed: {0}" -f $ollamaModel)
    }
    else {
        Write-Host "      [INFO] Installing offline Ollama model..."
        Write-Host ("      Source: {0}" -f $sourceModelStore)
        Write-Host ("      Target: {0}" -f $targetModelStore)
        Write-Host ("      Model : {0}" -f $ollamaModel)
        if (-not [IO.Path]::GetFullPath($sourceModelStore).Equals([IO.Path]::GetFullPath($targetModelStore), [StringComparison]::OrdinalIgnoreCase)) {
            Merge-ModelStore -Source $sourceModelStore -Target $targetModelStore
        }
        $targetStatus = Get-OllamaModelFileStatus -ModelStore $targetModelStore -ModelName $ollamaModel
        if (-not $targetStatus.Complete) {
            throw ("Offline model copy completed, but the target store is incomplete: {0}" -f $targetStatus.Reason)
        }
        Write-Ok ("Offline model files installed: {0}" -f $ollamaModel)
    }

    Write-Step 7 7 "Verifying the model through Ollama..."
    $tags = Get-OllamaTags $ollamaBaseUrl
    if ($null -eq $tags) {
        if ($ollamaBaseUrl -ne "http://127.0.0.1:11434" -and $ollamaBaseUrl -ne "http://localhost:11434") {
            throw "The configured OLLAMA_BASE_URL is offline. Automatic verification startup is limited to the local default endpoint."
        }
        $temporaryOllama = Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Minimized -PassThru
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            Start-Sleep -Seconds 1
            $tags = Get-OllamaTags $ollamaBaseUrl
            if ($null -ne $tags) { break }
            if ($temporaryOllama.HasExited) { break }
        }
    }
    if ($null -eq $tags) {
        throw "Ollama could not be started for offline model verification."
    }
    $modelNames = @(Get-OllamaModelNames $tags)
    if ($modelNames -notcontains $ollamaModel) {
        throw ("Offline model store was copied, but Ollama cannot find {0}" -f $ollamaModel)
    }
    Write-Ok $ollamaModel
    Stop-TemporaryOllama

    foreach ($requiredPath in @(
        (Join-Path $repoRoot "dashboard\app.py"),
        (Join-Path $repoRoot "START_WINDOWS.bat"),
        (Join-Path $repoRoot "WINDOWS_CHECK.bat")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw ("Required project file is missing: {0}" -f $requiredPath)
        }
    }

    Write-Host ""
    Write-Host "[OK] Dashboard" -ForegroundColor Green
    Write-Host "[OK] Windows launcher" -ForegroundColor Green
    Write-Host ""
    Write-Host "INSTALLATION COMPLETE" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next step:"
    Write-Host "Double-click START_WINDOWS.bat"
    exit 0
}
catch {
    Stop-TemporaryOllama
    if ($venvCreatedThisRun -and (Test-Path -LiteralPath $venvDirectory)) {
        Remove-Item -LiteralPath $venvDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host ""
    Write-Host ("[ERROR] {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}
