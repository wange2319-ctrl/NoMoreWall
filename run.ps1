[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "首次运行，正在初始化环境..."
    & (Join-Path $ProjectRoot "setup.ps1") -SkipRun
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "local_proxy.conf"))) {
    Set-Content -LiteralPath (Join-Path $ProjectRoot "local_proxy.conf") -Value "" -Encoding utf8NoBOM
}

Write-Host "开始轮换两期订阅..."
& $Python archive_periods.py rotate
if ($LASTEXITCODE -ne 0) {
    Write-Host "订阅期轮换失败。" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "开始抓取并合并公开节点。完整执行通常需要 1-5 分钟。`n"
& $Python fetch.py
$Code = $LASTEXITCODE
if ($Code -ne 0) {
    Write-Host "抓取失败，退出码：$Code" -ForegroundColor Red
    exit $Code
}

Write-Host "`n开始按纯净度和可用度筛选每类前 10 个节点..."
& $Python quality_filter.py
$Code = $LASTEXITCODE
if ($Code -ne 0) {
    Write-Host "精选排序失败，退出码：$Code" -ForegroundColor Red
    exit $Code
}

Write-Host "`n固定最新两期订阅..."
& $Python archive_periods.py snapshot
if ($LASTEXITCODE -ne 0) {
    Write-Host "订阅快照保存失败。" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "`n生成结果："
Get-ChildItem -LiteralPath $ProjectRoot -Filter "list*" -File |
    Select-Object Name, Length, LastWriteTime |
    Format-Table -AutoSize
Write-Host "订阅产物位于：$ProjectRoot"
