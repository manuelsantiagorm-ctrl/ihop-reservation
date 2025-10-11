# scripts/pg_backup.ps1  (PostgreSQL 15, Windows, robusto con logs y pre-check)
$ErrorActionPreference = "Stop"

# ===== CONFIG =====
$PG_DUMP = "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe"
$PSQL    = "C:\Program Files\PostgreSQL\15\bin\psql.exe"

$env:PGPASSWORD = "BD"        # <-- tu pass
$DB_NAME = "ihop_db"          # <-- base correcta
$DB_USER = "postgres"
$DB_HOST = "127.0.0.1"
$DB_PORT = "5432"
# ===================

# Validaciones rápidas
if (-not (Test-Path -LiteralPath $PG_DUMP)) { Write-Error "No se encontró pg_dump en: $PG_DUMP" }
if (-not (Test-Path -LiteralPath $PSQL))    { Write-Error "No se encontró psql en: $PSQL" }

# Carpetas
$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $BaseDir
New-Item -ItemType Directory -Force -Path "..\backups" | Out-Null
New-Item -ItemType Directory -Force -Path "..\logs"    | Out-Null

$STAMP = Get-Date -Format "yyyyMMdd-HHmmss"
$OUT   = "..\backups\backup_${DB_NAME}_$STAMP.dump"
$ERR   = "..\logs\pg_dump_$STAMP.err.txt"

Write-Host "== Pre-check conexión =="
$checkArgs = @("-h",$DB_HOST,"-p",$DB_PORT,"-U",$DB_USER,"-d",$DB_NAME,"-c","SELECT 1;")
$check = Start-Process -FilePath $PSQL -ArgumentList $checkArgs -NoNewWindow -PassThru -Wait -RedirectStandardError $ERR
if ($check.ExitCode -ne 0) {
  Write-Error "Fallo el pre-check de conexión a '$DB_NAME'. Revisa el log: $ERR"
}

Write-Host "== Ejecutando pg_dump de '$DB_NAME' =="
$dumpArgs = @("-h",$DB_HOST,"-p",$DB_PORT,"-U",$DB_USER,"-F","c","-f",$OUT,$DB_NAME)
$proc = Start-Process -FilePath $PG_DUMP -ArgumentList $dumpArgs -NoNewWindow -PassThru -Wait -RedirectStandardError $ERR

if ($proc.ExitCode -ne 0) {
  Write-Error "pg_dump salió con código $($proc.ExitCode). Revisa el log: $ERR"
}

if (-not (Test-Path -LiteralPath $OUT)) { Write-Error "No se generó el archivo: $OUT" }

$size = (Get-Item -LiteralPath $OUT).Length
if ($size -le 0) { Write-Error "Backup con tamaño 0. Revisa el log: $ERR" }

Write-Host "✅ Backup listo: $OUT  (tamaño: $([math]::Round($size/1MB,2)) MB)"

# Retención 14 días (opcional)
Get-ChildItem "..\backups\backup_*.dump" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | Remove-Item -Force
