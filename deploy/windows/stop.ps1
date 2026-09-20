$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "common.ps1")
Initialize-Utf8Console

$repoRoot = Get-ProjectRoot
$runtimeDirectory = Get-RuntimeDirectory $repoRoot
$script:errorCount = 0

function Stop-ManagedProjectService {
    param(
        [string]$Name,
        [string]$PidPath
    )
    $process = Get-ManagedProjectProcess $PidPath $repoRoot
    if ($null -eq $process) {
        Remove-StalePidFile $PidPath
        Write-Host ("[OK] {0}: not running" -f $Name)
        return
    }
    $processId = [int]$process.ProcessId
    & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host ("[OK] {0}: stopped PID {1}" -f $Name, $processId) -ForegroundColor Green
        Remove-StalePidFile $PidPath
    }
    else {
        Write-Host ("[ERROR] {0}: failed to stop PID {1}" -f $Name, $processId) -ForegroundColor Red
        $script:errorCount++
    }
}

Write-Host "Stopping LD6002C project services..." -ForegroundColor Cyan
Stop-ManagedProjectService "AI Live Monitor" (Join-Path $runtimeDirectory "dashboard.pid")
Stop-ManagedProjectService "Radar service" (Join-Path $runtimeDirectory "radar.pid")
Remove-StalePidFile (Join-Path $runtimeDirectory "radar.ready")

$ollamaPidPath = Join-Path $runtimeDirectory "ollama.pid"
$ollamaPathState = Join-Path $runtimeDirectory "ollama.path"
$ollamaProcessId = Read-PidFile $ollamaPidPath
if ($null -eq $ollamaProcessId) {
    Write-Host "[OK] Ollama: not started by this project"
    Remove-StalePidFile $ollamaPidPath
    Remove-StalePidFile $ollamaPathState
}
else {
    $ollamaProcess = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $ollamaProcessId) -ErrorAction SilentlyContinue
    $isOwnedOllama = $false
    $expectedOllamaPath = ""
    if (Test-Path -LiteralPath $ollamaPathState -PathType Leaf) {
        $expectedOllamaPath = (Get-Content -LiteralPath $ollamaPathState -Raw).Trim()
    }
    if ($null -ne $ollamaProcess -and -not [string]::IsNullOrWhiteSpace($expectedOllamaPath)) {
        $name = [string]$ollamaProcess.Name
        $commandLine = [string]$ollamaProcess.CommandLine
        $executablePath = [string]$ollamaProcess.ExecutablePath
        $isOwnedOllama = $name.StartsWith("ollama", [StringComparison]::OrdinalIgnoreCase) -and `
            $commandLine.IndexOf("serve", [StringComparison]::OrdinalIgnoreCase) -ge 0 -and `
            $executablePath.Equals($expectedOllamaPath, [StringComparison]::OrdinalIgnoreCase)
    }
    if ($isOwnedOllama) {
        Stop-Process -Id $ollamaProcessId -Force -ErrorAction SilentlyContinue
        Write-Host ("[OK] Ollama: stopped PID {0} (started by this project)" -f $ollamaProcessId) -ForegroundColor Green
    }
    else {
        Write-Host "[WARN] Ollama PID state was stale or did not match; no process was killed." -ForegroundColor Yellow
    }
    Remove-StalePidFile $ollamaPidPath
    Remove-StalePidFile $ollamaPathState
}

if ($script:errorCount -gt 0) {
    exit 1
}
Write-Host "Project services stopped. Other Python and Ollama processes were not touched." -ForegroundColor Green
exit 0
