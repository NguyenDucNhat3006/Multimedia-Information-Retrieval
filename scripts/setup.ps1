# Tạo venv riêng và cài đúng lockfile; cache/TEMP dùng workspace để không đầy ổ C.
param([switch]$CoreOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PIP_CACHE_DIR = Join-Path $projectRoot '.runtime\pip-cache'
$env:TEMP = Join-Path $projectRoot '.runtime\tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Không tạo được venv Python 3.12' }
}
if ($CoreOnly) {
    & $projectPython -m pip install -e '.[test]'
} else {
    & $projectPython -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -eq 0) { & $projectPython -m pip install --no-deps -e . }
}
if ($LASTEXITCODE -ne 0) { throw 'Cài Python dependencies thất bại' }
Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci thất bại' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build thất bại' }
} finally { Pop-Location }
Write-Output 'Setup xong. Chạy .\scripts\start.ps1 để mở http://127.0.0.1:8000'
