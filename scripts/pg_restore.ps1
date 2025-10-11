# scripts/pg_restore.ps1  (PostgreSQL 15, Windows)
# Uso: .\pg_restore.ps1 ..\backups\backup_ihop_db_YYYYMMDD-HHMMSS.dump ihop_restore

param(
  [Parameter(Mandatory=$true)][string]$BackupFile,
  [Parameter(Mandatory=$true)][string]$TargetDb
)

$ErrorActionPreference = "Stop"

# --- Ajusta credenciales si usas usuario distinto ---
$env:PGPASSWORD = "BD"
$DB_USER = "postgres"
$DB_HOST = "127.0.0.1"
$DB_PORT = "5432"

$PG_RESTORE = "C:\Program Files\PostgreSQL\15\bin\pg_restore.exe"
$PSQL       = "C:\Program Files\PostgreSQL\15\bin\psql.exe"
$CREATEDB   = "C:\Program Files\PostgreSQL\15\bin\createdb.exe"
$DROPDB     = "C:\Program Files\PostgreSQL\15\bin\dropdb.exe"

if (-not (Test-Path $BackupFile)) { Write-Error "No existe el archivo: $BackupFile" }

# Crea carpeta de logs
$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Force -Path "..\logs" | Out-Null
$STAMP = Get-Date -Format "yyyyMMdd-HHmmss"
$ERR   = "..\logs\pg_restore_$STAMP.err.txt"

# (Opcional) dropear DB destino si existe
try {
  & $DROPDB -h $DB_HOST -p $DB_PORT -U $DB_USER $TargetDb 2>$null
} catch {}

# Crear DB destino
& $CREATEDB -h $DB_HOST -p $DB_PORT -U $DB_USER $TargetDb

# Restaurar
$Args = @("-h",$DB_HOST,"-p",$DB_PORT,"-U",$DB_USER,"-d",$TargetDb,"--clean",$BackupFile)
$proc = Start-Process -FilePath $PG_RESTORE -ArgumentList $Args -NoNewWindow -PassThru -Wait -RedirectStandardError $ERR

if ($proc.ExitCode -ne 0) {
  Write-Error "pg_restore salió con código $($proc.ExitCode). Revisa el log: $ERR"
}

# Verificación básica
& $PSQL -h $DB_HOST -p $DB_PORT -U $DB_USER -d $TargetDb -c "\dt"

Write-Host "✅ Restauración completa en DB '$TargetDb'. Log: $ERR"
