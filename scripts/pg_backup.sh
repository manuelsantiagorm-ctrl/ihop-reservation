#!/usr/bin/env bash
set -euo pipefail

# Variables (ajusta según tu setup/local/env)
export PGPASSWORD="${POSTGRES_PASSWORD:-tu_password}"
DB_NAME="${POSTGRES_DB:-ihop}"
DB_USER="${POSTGRES_USER:-ihop_user}"
DB_HOST="${POSTGRES_HOST:-127.0.0.1}"
DB_PORT="${POSTGRES_PORT:-5432}"

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="backup_${DB_NAME}_${STAMP}.sql.gz"

pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -F p "$DB_NAME" | gzip > "$OUT"

echo "Backup listo: $OUT"



export PGPASSWORD="mi_password"
DB_NAME="ihop"
DB_USER="postgres"
DB_HOST="127.0.0.1"
DB_PORT="5432"
