#!/usr/bin/env bash
#
# Restore the SQLite database from a backup produced by backup-sqlite.sh.
#
#   sudo ./deploy/gx10/restore-sqlite.sh /opt/local-ai-model-lab/data/backups/model-lab-20250801-120000.db.gz
#
set -euo pipefail

ROOT="${AML_ROOT:-/opt/local-ai-model-lab}"
DB="${ROOT}/data/model-lab.db"
BACKUP="${1:-}"

if [ -z "$BACKUP" ]; then
  echo "usage: restore-sqlite.sh <backup-file.db.gz>" >&2
  exit 1
fi
if [ ! -f "$BACKUP" ]; then
  echo "restore: backup not found: $BACKUP" >&2
  exit 1
fi

# Stop the portal so the live database is not locked during the swap.
systemctl stop ai-model-lab.service
gunzip -c "$BACKUP" > "$DB"
systemctl start ai-model-lab.service

echo "restore: ${BACKUP} applied to ${DB}"
systemctl status ai-model-lab.service --no-pager -n 0 || true
