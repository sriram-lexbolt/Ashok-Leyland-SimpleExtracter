param([ValidateRange(1, 65535)][int]$Port = 8000, [switch]$Install, [switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$environmentPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $environmentPython)) {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($systemPython) {
        & $systemPython.Source -m venv .venv
    } elseif ($pythonLauncher) {
        & $pythonLauncher.Source -3 -m venv .venv
    } else {
        throw 'Install Python 3.11 or newer, then run the launcher again.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
    $Install = $true
}
& $environmentPython -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
if (-not $Install) {
    & $environmentPython -c 'import importlib.util, sys; sys.exit(0 if all(importlib.util.find_spec(name) for name in sys.argv[1:]) else 1)' fastapi uvicorn multipart pdfplumber pypdfium2 PIL
    if ($LASTEXITCODE -ne 0) { $Install = $true }
}
if ($Install) {
    & $environmentPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try {
    $listener.Start()
} catch {
    throw "Port $Port is already in use. Close the other application window or run start.cmd -Port 8001."
} finally {
    $listener.Stop()
}
$url = "http://127.0.0.1:$Port"
$browserJob = $null
if ($OpenBrowser) {
    $browserJob = Start-Job -ArgumentList $url -ScriptBlock {
        param($AppUrl)
        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline) {
            try {
                $response = Invoke-WebRequest -Uri "$AppUrl/api/health" -UseBasicParsing -TimeoutSec 2
                if ($response.StatusCode -eq 200) {
                    Start-Process $AppUrl
                    return
                }
            } catch { }
            Start-Sleep -Milliseconds 500
        }
    }
}
Write-Host "Starting Jags AL Data Extracter at $url"
Write-Host 'Keep this window open while using the application. Press Ctrl+C to stop it.'
try {
    & $environmentPython -m uvicorn app:app --host 127.0.0.1 --port $Port
    $serverExit = $LASTEXITCODE
} finally {
    if ($browserJob) {
        Stop-Job -Job $browserJob
        Remove-Job -Job $browserJob
    }
}
exit $serverExit
