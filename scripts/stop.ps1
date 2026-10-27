# Chỉ dừng process Uvicorn được ghi bởi workspace, kiểm tra lại command trước tránh PID reuse.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $projectRoot '.runtime\server.json'
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Output 'Không có server PID của workspace'; return }
$record = Get-Content -LiteralPath $pidPath -Raw | ConvertFrom-Json
if ([IO.Path]::GetFullPath($record.root) -ne [IO.Path]::GetFullPath($projectRoot)) { throw 'PID record không thuộc workspace' }
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.pid)"
if ($process -and $process.CommandLine -like '*uvicorn*app.main:create_app*' -and $process.CommandLine -like "*$projectRoot*") {
    # Python launcher có thể có child; chỉ dừng child trỏ cùng entrypoint, không process khác.
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $($record.pid)" | Where-Object { $_.CommandLine -like '*uvicorn*app.main:create_app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }
    Stop-Process -Id $record.pid -ErrorAction SilentlyContinue
} elseif ($process) { throw 'PID đã đổi chủ hoặc command khác; không tự dừng' }
Remove-Item -LiteralPath $pidPath
Write-Output 'Đã dừng server của workspace'
