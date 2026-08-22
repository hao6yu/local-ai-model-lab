#!/usr/bin/env bash
#
# Snapshot the SQLite database used by the portal. The live database is copied
# with SQLite's .backup() API (a consistent read-only snapshot even while the
# portal is running), compressed, and pruned to the last $AML_KEEP backups.
#
#   AML_ROOT=/opt/local-ai-model-lab   # defaults to the install root
#   AML_KEEP=30
#   ./deploy/gx10/backup-sqlite.sh
#
set -euo pipefail

ROOT="${AML_ROOT:-/opt/local-ai-model-lab}"
DATA_DIR="${ROOT}/data"
BACKUP_DIR="${DATA_DIR}/backups"
DB="${DATA_DIR}/model-lab.db"
KEEP="${AML_KEEP:-30}"

mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
TARGET="${BACKUP_DIR}/model-lab-${TS}.db"

"${ROOT}/backend/.venv/bin/python" - "$DB" "$TARGET" <<'PY'
import sqlite3
import sys

src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as source:
    with sqlite3.connect(dst) as target:
        source.backup(target)
PY

gzip -f "$TARGET"
ARCHIVE="${TARGET}.gz"

# Keep the newest $KEEP archives, delete the rest.
ls -1t "${BACKUP_DIR}"/model-lab-*.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f

echo "backup: $ARCHIVE"
