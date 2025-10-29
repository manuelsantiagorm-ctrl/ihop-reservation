<# 
Deploy local/prod para IHOP (Windows).

Flujo:
  1) Backup de Postgres (opcional)
  2) migrate
  3) collectstatic
  4) check --deploy
  5) Health check HTTP (opcional)

Uso:
  .\scripts\deploy_windows.ps1 -Env dev -HealthUrl "http://127.0.0.1:8000/"
  .\scripts\deploy_windows.ps1 -Env prod -HealthUrl "https://tu-dominio.com/"
  .\scripts\deploy_windows.ps1 -Env dev -NoBackup -HealthUrl "http://127.0.0.1:8000/"
#>

param(
  [ValidateSet("dev","prod")]
  [string]$Env = "dev",
  [switch]$NoBackup = $false,
  [string]$HealthUrl = "",
  [string]$VenvPath = ""
)

$ErrorActionPreference = "Stop"

# Ir a la raíz del repo
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $root

Write-Host "== IHOP Deploy (Windows) ==" -ForegroundColor Cyan
Write-Host ("Raíz: {0}" -f $root)
Write-Host ("Entorno lógico (solo log): {0}" -f $Env)

# 0) Activar venv (opcional)
if ($VenvPath -and (Test-Path $VenvPath)) {
  Write-Host ("Activando venv: {0}" -f $VenvPath)
  . $VenvPath
} else {
  Write-Host "Venv: usando la sesión actual." -ForegroundColor DarkGray
}

# Helpers: cargar .env en un diccionario
function Get-DotEnv {
  param([string]$Path = ".env")
  $vars = @{}
  if (Test-Path $Path) {
    Get-Content -Path $Path | ForEach-Object {
      $line = $_.Trim()
      if (-not $line) { return }
      if ($line.StartsWith("#")) { return }
      $eq = $line.IndexOf("=")
      if ($eq -gt 0) {
        $k = $line.Substring(0,$eq).Trim()
        $v = $line.Substring($eq+1).Trim()
        # Quitar comillas si las hay
        if (($v.StartsWith("'") -and $v.EndsWith("'")) -or ($v.StartsWith('"') -and $v.EndsWith('"'))) {
          $v = $v.Substring(1, $v.Length-2)
        }
        $vars[$k] = $v
      }
    }
  }
  return $vars
}

$dotenv = Get-DotEnv ".env"

function Get-EnvOrDotEnv {
  param([string]$Key, [string]$Default = "")
  $envVal = [System.Environment]::GetEnvironmentVariable($Key)
  if ($envVal) { return $envVal }
  if ($dotenv.ContainsKey($Key)) { return $dotenv[$Key] }
  return $Default
}
# 1) Backup (opcional)
if (-not $NoBackup) {
  # Detectar pg_dump
  $pgDump = (Get-Command pg_dump -ErrorAction SilentlyContinue)
  if (-not $pgDump) {
    $candidatos = @(
      "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
      "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe",
      "C:\Program Files\PostgreSQL\14\bin\pg_dump.exe"
    )
    foreach ($c in $candidatos) {
      if (Test-Path $c) { $pgDump = $c; break }
    }
  } else {
    $pgDump = $pgDump.Source
  }

  if (-not $pgDump) {
    Write-Warning "pg_dump no encontrado. Se omite backup esta vez. (Agrega PostgreSQL\\bin al PATH para habilitarlo)"
  } else {
    $dbUrl  = Get-EnvOrDotEnv -Key "DATABASE_URL" -Default ""
    $dbName = Get-EnvOrDotEnv -Key "DB_NAME" -Default ""
    $dbUser = Get-EnvOrDotEnv -Key "DB_USER" -Default ""
    $dbHost = Get-EnvOrDotEnv -Key "DB_HOST" -Default "localhost"
    $dbPort = Get-EnvOrDotEnv -Key "DB_PORT" -Default "5432"
    $dbPass = Get-EnvOrDotEnv -Key "DB_PASSWORD" -Default ""

    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $bk = "backup_pg_${ts}.sql"
    Write-Host ("Creando backup de Postgres -> {0}" -f $bk) -ForegroundColor Yellow

    if ($dbUrl) {
      $env:PGPASSWORD = ""
      & "$pgDump" --file "$bk" --clean --if-exists --no-owner --no-privileges "$dbUrl"
    } elseif ($dbName -and $dbUser) {
      if ($dbPass) { $env:PGPASSWORD = $dbPass }
      & "$pgDump" --file "$bk" --clean --if-exists --no-owner --no-privileges `
        --host "$dbHost" --port "$dbPort" --username "$dbUser" --dbname "$dbName"
    } else {
      Write-Warning "No hay DATABASE_URL ni DB_* suficientes; se omite backup."
    }
  }
} else {
  Write-Host "Backup desactivado (-NoBackup)." -ForegroundColor DarkGray
}


# 2) Migraciones
Write-Host "Aplicando migraciones…" -ForegroundColor Yellow
python manage.py migrate

# 3) Estáticos
Write-Host "Recolectando estáticos…" -ForegroundColor Yellow
python manage.py collectstatic --noinput

# 4) Check de despliegue
Write-Host "Revisando configuración de despliegue…" -ForegroundColor Yellow
python manage.py check --deploy

# 5) Health check (opcional)
if ($HealthUrl) {
  try {
    Write-Host ("Health check -> {0}" -f $HealthUrl) -ForegroundColor Yellow
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 10
    $code = $resp.StatusCode
    if ($code -ge 200 -and $code -lt 400) {
      Write-Host ("OK ({0}) - site responded." -f $code) -ForegroundColor Green
    } else {
      Write-Warning ("Site responded with HTTP {0}." -f $code)
    }
  } catch {
    Write-Warning ("Health check failed: {0}" -f $_.Exception.Message)
  }
} else {
  Write-Host "Health check skipped (no -HealthUrl)." -ForegroundColor DarkGray
}

Write-Host "== Deploy terminado ==" -ForegroundColor Green
