[CmdletBinding()]
param(
    [switch]$SkipRun
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "[1/3] 创建 Python 虚拟环境..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败，请确认已安装 Python 3.10+。" }
} else {
    Write-Host "[1/3] Python 虚拟环境已存在。"
}

Write-Host "[2/3] 安装 / 校验依赖..."
& $Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败。" }

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "local_proxy.conf"))) {
    Set-Content -LiteralPath (Join-Path $ProjectRoot "local_proxy.conf") -Value "" -Encoding utf8NoBOM
    Write-Host "已创建空白 local_proxy.conf（直连模式）。"
}

Write-Host "[3/3] 环境准备完成。"
if (-not $SkipRun) {
    & $Python fetch.py
    exit $LASTEXITCODE
}
