# Chạy một Uvicorn worker ẩn, log và PID của riêng workspace; không tự chạy ingest.
param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$runtimeRoot = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Chạy scripts/setup.ps1 trước' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) { throw 'Chạy npm.cmd run build trong frontend trước' }
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw "Port $Port đã được dùng. Dùng -Port khác hoặc dừng process đúng workspace." }
$env:HF_HOME = Join-Path $projectRoot 'data\model-cache\hf'
$env:OMP_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '4'
$process = Start-Process -FilePath $projectPython -ArgumentList @('-m','uvicorn','app.main:create_app','--factory','--host','127.0.0.1','--port',"$Port",'--workers','1') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot 'server.log') -RedirectStandardError (Join-Path $runtimeRoot 'server-error.log')
$pidPath = Join-Path $runtimeRoot 'server.json'
@{pid=$process.Id;root=$projectRoot;port=$Port} | ConvertTo-Json | Set-Content -LiteralPath $pidPath -Encoding UTF8
Write-Output "Đã khởi chạy PID $($process.Id): http://127.0.0.1:$Port · log .runtime/server-error.log"
