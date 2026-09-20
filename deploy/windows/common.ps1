Set-StrictMode -Version Latest

function Get-ProjectRoot {
    return [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}

function Initialize-Utf8Console {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [Console]::InputEncoding = $utf8
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
}

function Write-Step {
    param(
        [int]$Number,
        [int]$Total,
        [string]$Message
    )
    Write-Host ""
    Write-Host ("[{0}/{1}] {2}" -f $Number, $Total, $Message) -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host ("      [OK] {0}" -f $Message) -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host ("      [WARN] {0}" -f $Message) -ForegroundColor Yellow
}

function Get-PythonExecutable {
    param([string]$RepoRoot)
    return Join-Path $RepoRoot ".venv\Scripts\python.exe"
}

function Get-RuntimeDirectory {
    param([string]$RepoRoot)
    $runtimeDirectory = Join-Path $RepoRoot "data\windows-runtime"
    if (-not (Test-Path -LiteralPath $runtimeDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
    }
    return $runtimeDirectory
}

function Test-TcpPort {
    param(
        [string]$HostName = "127.0.0.1",
        [int]$Port,
        [int]$TimeoutMilliseconds = 500
    )
    $client = New-Object Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) {
            return $false
        }
        $client.EndConnect($result)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Test-HttpEndpoint {
    param(
        [string]$Uri,
        [int]$TimeoutSeconds = 2
    )
    try {
        Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec $TimeoutSeconds | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Get-OllamaTags {
    param([string]$BaseUrl)
    try {
        return Invoke-RestMethod -Uri ($BaseUrl.TrimEnd('/') + "/api/tags") -Method Get -TimeoutSec 2
    }
    catch {
        return $null
    }
}

function Get-OllamaModelNames {
    param([object]$Tags)
    $names = @()
    if ($null -eq $Tags) {
        return $names
    }
    $modelsProperty = $Tags.PSObject.Properties["models"]
    if ($null -eq $modelsProperty -or $null -eq $modelsProperty.Value) {
        return $names
    }
    foreach ($model in @($modelsProperty.Value)) {
        if ($null -eq $model) {
            continue
        }
        $nameProperty = $model.PSObject.Properties["name"]
        if ($null -ne $nameProperty -and -not [string]::IsNullOrWhiteSpace([string]$nameProperty.Value)) {
            $names += [string]$nameProperty.Value
        }
        $modelProperty = $model.PSObject.Properties["model"]
        if ($null -ne $modelProperty -and -not [string]::IsNullOrWhiteSpace([string]$modelProperty.Value)) {
            $names += [string]$modelProperty.Value
        }
    }
    return @($names | Select-Object -Unique)
}

function Get-OllamaModelStore {
    try {
        if (-not [string]::IsNullOrWhiteSpace($env:OLLAMA_MODELS)) {
            $expanded = [Environment]::ExpandEnvironmentVariables($env:OLLAMA_MODELS.Trim())
            return [IO.Path]::GetFullPath($expanded)
        }
        if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
            return $null
        }
        return [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE ".ollama\models"))
    }
    catch {
        return $null
    }
}

function Get-OllamaManifestPath {
    param(
        [string]$ModelStore,
        [string]$ModelName
    )
    if ([string]::IsNullOrWhiteSpace($ModelStore) -or [string]::IsNullOrWhiteSpace($ModelName)) {
        return $null
    }

    $repository = $ModelName.Trim()
    $tag = "latest"
    $slashIndex = $repository.LastIndexOf("/")
    $colonIndex = $repository.LastIndexOf(":")
    if ($colonIndex -gt $slashIndex) {
        $tag = $repository.Substring($colonIndex + 1)
        $repository = $repository.Substring(0, $colonIndex)
    }

    $parts = @($repository -split "/")
    if ($parts.Count -eq 1) {
        $namespace = "library"
        $name = $parts[0]
    }
    elseif ($parts.Count -eq 2) {
        $namespace = $parts[0]
        $name = $parts[1]
    }
    else {
        return $null
    }
    foreach ($segment in @($namespace, $name, $tag)) {
        if ([string]::IsNullOrWhiteSpace($segment) -or $segment -eq "." -or $segment -eq "..") {
            return $null
        }
    }
    return Join-Path $ModelStore ("manifests\registry.ollama.ai\{0}\{1}\{2}" -f $namespace, $name, $tag)
}

function Get-OllamaModelFileStatus {
    param(
        [string]$ModelStore,
        [string]$ModelName
    )
    $manifestPath = Get-OllamaManifestPath $ModelStore $ModelName
    if ([string]::IsNullOrWhiteSpace($manifestPath) -or -not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        return [PSCustomObject]@{
            Complete = $false
            ManifestPath = $manifestPath
            MissingBlobs = @()
            Reason = "manifest missing"
        }
    }

    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    }
    catch {
        return [PSCustomObject]@{
            Complete = $false
            ManifestPath = $manifestPath
            MissingBlobs = @()
            Reason = "manifest is invalid JSON"
        }
    }

    $digests = @()
    $configProperty = $manifest.PSObject.Properties["config"]
    if ($null -ne $configProperty -and $null -ne $configProperty.Value) {
        $digestProperty = $configProperty.Value.PSObject.Properties["digest"]
        if ($null -ne $digestProperty) {
            $digests += [string]$digestProperty.Value
        }
    }
    $layersProperty = $manifest.PSObject.Properties["layers"]
    if ($null -ne $layersProperty -and $null -ne $layersProperty.Value) {
        foreach ($layer in @($layersProperty.Value)) {
            if ($null -eq $layer) { continue }
            $digestProperty = $layer.PSObject.Properties["digest"]
            if ($null -ne $digestProperty) {
                $digests += [string]$digestProperty.Value
            }
        }
    }
    $digests = @($digests | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    if ($digests.Count -eq 0) {
        return [PSCustomObject]@{
            Complete = $false
            ManifestPath = $manifestPath
            MissingBlobs = @()
            Reason = "manifest contains no blob digests"
        }
    }

    $missingBlobs = @()
    foreach ($digest in $digests) {
        if ($digest -notmatch '^sha256:[0-9a-fA-F]{64}$') {
            $missingBlobs += $digest
            continue
        }
        $blobName = $digest.Replace(":", "-")
        $blobPath = Join-Path $ModelStore ("blobs\{0}" -f $blobName)
        if (-not (Test-Path -LiteralPath $blobPath -PathType Leaf)) {
            $missingBlobs += $digest
            continue
        }
        $blob = Get-Item -LiteralPath $blobPath -ErrorAction SilentlyContinue
        if ($null -eq $blob -or $blob.Length -le 0) {
            $missingBlobs += $digest
        }
    }

    return [PSCustomObject]@{
        Complete = ($missingBlobs.Count -eq 0)
        ManifestPath = $manifestPath
        MissingBlobs = @($missingBlobs)
        Reason = $(if ($missingBlobs.Count -eq 0) { "complete" } else { "one or more blobs are missing" })
    }
}

function Get-OllamaExecutable {
    param([string]$RepoRoot)
    $command = Get-Command "ollama.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $candidates += Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    }
    $candidates += Join-Path $RepoRoot "runtime\ollama\ollama.exe"
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

function Get-FfplayExecutable {
    param([string]$RepoRoot)
    $command = Get-Command "ffplay.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $RepoRoot "runtime\ffmpeg\bin\ffplay.exe"),
        (Join-Path $RepoRoot "vendor\ffmpeg\bin\ffplay.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

function ConvertTo-QuotedArgument {
    param([string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Start-ProjectWindow {
    param(
        [string]$RunnerPath,
        [string]$Service,
        [string]$RepoRoot,
        [string]$PythonExe,
        [string]$Mode = "serial",
        [string]$RadarPort = "",
        [int]$Baudrate = 115200,
        [string]$OllamaBaseUrl = "http://127.0.0.1:11434",
        [string]$OllamaModel = "qwen3:0.6b",
        [bool]$AudioEnabled = $true,
        [int]$AlarmVolume = 100,
        [int]$DashboardPort = 8501
    )
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-NoExit",
        "-File", $RunnerPath,
        "-Service", $Service,
        "-RepoRoot", $RepoRoot,
        "-PythonExe", $PythonExe,
        "-Mode", $Mode,
        "-RadarPort", $RadarPort,
        "-Baudrate", $Baudrate.ToString(),
        "-OllamaBaseUrl", $OllamaBaseUrl,
        "-OllamaModel", $OllamaModel,
        "-AudioMode", $(if ($AudioEnabled) { "enabled" } else { "disabled" }),
        "-AlarmVolume", $AlarmVolume.ToString(),
        "-DashboardPort", $DashboardPort.ToString()
    )
    $argumentLine = ($arguments | ForEach-Object { ConvertTo-QuotedArgument ([string]$_) }) -join " "
    return Start-Process -FilePath "powershell.exe" -ArgumentList $argumentLine -WorkingDirectory $RepoRoot -PassThru
}

function Read-PidFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    $text = (Get-Content -LiteralPath $Path -Raw).Trim()
    $processId = 0
    if (-not [int]::TryParse($text, [ref]$processId)) {
        return $null
    }
    return $processId
}

function Get-ManagedProjectProcess {
    param(
        [string]$PidPath,
        [string]$RepoRoot
    )
    $processId = Read-PidFile $PidPath
    if ($null -eq $processId) {
        return $null
    }
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $processId) -ErrorAction SilentlyContinue
    if ($null -eq $process -or [string]::IsNullOrWhiteSpace($process.CommandLine)) {
        return $null
    }
    $commandLine = [string]$process.CommandLine
    if ($commandLine.IndexOf("run-service.ps1", [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        return $null
    }
    if ($commandLine.IndexOf($RepoRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        return $null
    }
    return $process
}

function Remove-StalePidFile {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        Remove-Item -LiteralPath $Path -Force
    }
}
