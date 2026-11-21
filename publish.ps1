[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoUrl,
    [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

if ($RepoUrl -notmatch '^https://github\.com/.+/.+\.git$') {
    throw "请填写形如 https://github.com/用户名/仓库名.git 的地址。"
}

$InsideWorkTree = git rev-parse --is-inside-work-tree 2>$null
if ($LASTEXITCODE -ne 0 -or $InsideWorkTree -ne "true") {
    Write-Host "正在初始化 Git 仓库并创建首次提交..."
    git init -b main
    if ($LASTEXITCODE -ne 0) { throw "Git 仓库初始化失败。" }
    git config user.name "AutoMergeLocal"
    git config user.email "actions@github.com"
    git add -A
    git commit -m "AutoMergePublicNodes initial two-period snapshot"
    if ($LASTEXITCODE -ne 0) { throw "首次 Git 提交失败。" }
}

if ($PrepareOnly) {
    Write-Host "本地仓库已准备完成：$ProjectRoot" -ForegroundColor Green
    exit 0
}

$ExistingOrigin = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0 -and $ExistingOrigin) {
    git remote set-url origin $RepoUrl
} else {
    git remote add origin $RepoUrl
}

git branch -M main
git push -u origin main
if ($LASTEXITCODE -ne 0) { throw "推送失败，请检查 GitHub 登录状态和仓库地址，并确认远程仓库为空。" }

$Match = [regex]::Match($RepoUrl, '^https://github\.com/([^/]+)/([^/]+)\.git$')
Write-Host "`n推送完成。" -ForegroundColor Green
if ($Match.Success) {
    $Owner = $Match.Groups[1].Value
    $Repo = $Match.Groups[2].Value
    Write-Host "`n最终订阅地址（Clash Meta / Mihomo）：" -ForegroundColor Cyan
    Write-Host "https://raw.githubusercontent.com/$Owner/$Repo/main/list.best.meta.yml"
    Write-Host "`njsDelivr 加速地址：" -ForegroundColor Cyan
    Write-Host "https://cdn.jsdelivr.net/gh/$Owner/$Repo@main/list.best.meta.yml"
    Write-Host "`n上一期回退地址：" -ForegroundColor Cyan
    Write-Host "https://raw.githubusercontent.com/$Owner/$Repo/main/periods/previous/list.best.meta.yml"
}

Write-Host "`n只需再确认一次：" -ForegroundColor Yellow
Write-Host "打开仓库 Settings -> Actions -> General"
Write-Host "将 Workflow permissions 设为 Read and write permissions"
Write-Host "之后 Fetch 每 3 小时自动运行，只保留最新两期。"
