param()

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$IndexData = Join-Path $RepoRoot "index_data"
$EnvFile = Join-Path $RepoRoot ".env"

function Read-EnvValue($Path, $Name, $DefaultValue) {
    if (-not (Test-Path $Path)) {
        return $DefaultValue
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts[0].Trim() -eq $Name) {
            $value = $parts[1].Trim().Trim('"').Trim("'")
            if ($value) {
                return $value
            }
        }
    }

    return $DefaultValue
}

if (-not (Test-Path $IndexData)) {
    throw "index_data not found: $IndexData"
}

if (-not (Test-Path $EnvFile)) {
    Copy-Item -LiteralPath (Join-Path $RepoRoot ".env.example") -Destination $EnvFile
}

$HostName = if ($env:HOST) { $env:HOST } else { Read-EnvValue $EnvFile "HOST" "127.0.0.1" }
$Port = if ($env:PORT) { $env:PORT } else { Read-EnvValue $EnvFile "PORT" "8002" }

if (-not $HostName) {
    $HostName = "127.0.0.1"
}
if (-not $Port) {
    $Port = "8002"
}

$env:HOST = $HostName
$env:PORT = $Port
$env:ENV = if ($env:ENV) { $env:ENV } else { Read-EnvValue $EnvFile "ENV" "public" }
$env:RELOAD = if ($env:RELOAD) { $env:RELOAD } else { Read-EnvValue $EnvFile "RELOAD" "false" }
$env:DB_AUTO_SCHEMA = if ($env:DB_AUTO_SCHEMA) { $env:DB_AUTO_SCHEMA } else { "false" }

Set-Location $IndexData
python -m uvicorn api.main:app --host $HostName --port $Port
