param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8002
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvFile = Join-Path $RepoRoot ".env"
$DbFile = Join-Path $RepoRoot "data\GeniusStroke_v2.db"
$HealthUrl = "http://${HostName}:${Port}/health"

if (-not (Test-Path $EnvFile)) {
    throw "未找到 .env。请执行：Copy-Item .env.example .env"
}

if (-not (Test-Path $DbFile)) {
    throw "未找到数据库。请执行：python scripts\init_empty_db.py"
}

$response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
if ($response.StatusCode -ne 200) {
    throw "健康检查失败：HTTP $($response.StatusCode)"
}

Write-Host "本地检查通过：$HealthUrl"
