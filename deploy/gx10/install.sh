#!/usr/bin/env bash
#
# Reproducible install of the Local AI Model Lab portal onto the GX10.
#
# The portal is a single FastAPI process that serves both the API and the built
# React SPA on loopback (127.0.0.1:8081). Run it on the GX10 from the source
# checkout (or a copy) of this repository. Secrets live in
# /opt/local-ai-model-lab/backend/.env and are never shipped here.
#
#   AML_SRC=/path/to/repo        # defaults to this script's parent tree
#   INSTALL_ROOT=/opt/local-ai-model-lab
#   sudo ./deploy/gx10/install.sh
#
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/local-ai-model-lab}"
SRC="${AML_SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BACKEND_DIR="${INSTALL_ROOT}/backend"
VENV="${BACKEND_DIR}/.venv"
SERVICE_USER="ai-model-lab"
PORTAL_HOST="127.0.0.1"
PORTAL_PORT="8081"

log() { printf 'install: %s\n' "$*"; }

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

# --- validate source checkout ------------------------------------------------
if [ ! -f "${SRC}/backend/app/main.py" ] || [ ! -f "${SRC}/frontend/package.json" ]; then
  echo "install: $SRC is not a checkout of this repository (expect backend/ and frontend/)" >&2
  exit 1
fi
if [ "$INSTALL_ROOT" = "${SRC}" ]; then
  echo "install: INSTALL_ROOT must differ from the source checkout" >&2
  exit 1
fi

# --- required tooling --------------------------------------------------------
for tool in npm python3 rsync; do
  command -v "$tool" >/dev/null 2>&1 || { echo "install: missing required tool: $tool" >&2; exit 1; }
done
read -r node_major node_minor _ <<<"$(node --version | tr -d 'v')"
if [ "$node_major" -lt 18 ]; then
  echo "install: frontend build needs Node >= 18 (found $(node --version))" >&2
  exit 1
fi

# --- provision the code tree -------------------------------------------------
log "creating install tree at $INSTALL_ROOT"
$SUDO mkdir -p "$INSTALL_ROOT"
$SUDO chown "$(id -u):$(id -g)" "$INSTALL_ROOT"
$SUDO rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='.git' --exclude='frontend/dist' \
  "${SRC}/" "${INSTALL_ROOT}/"

# --- dedicated service user --------------------------------------------------
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  log "creating service user $SERVICE_USER"
  $SUDO useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# --- python environment ------------------------------------------------------
log "creating python venv"
$SUDO python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "${BACKEND_DIR}/requirements.txt"

# --- frontend build ----------------------------------------------------------
log "building frontend"
cd "${INSTALL_ROOT}/frontend"
npm ci
npm run build

# --- .env (endpoints + optional keys; never committed) -----------------------
ENV_FILE="${BACKEND_DIR}/.env"
if [ ! -f "$ENV_FILE" ]; then
  log "creating ${ENV_FILE} from the shipped example — edit it with the real endpoints"
  $SUDO cp "${SRC}/backend/.env.example" "$ENV_FILE"
fi

# --- systemd units -----------------------------------------------------------
log "installing systemd units"
$SUDO cp "${SRC}/deploy/gx10/ai-model-lab.service" /etc/systemd/system/ai-model-lab.service
$SUDO cp "${SRC}/deploy/gx10/health.service"       /etc/systemd/system/health.service
$SUDO cp "${SRC}/deploy/gx10/health.timer"         /etc/systemd/system/health.timer
$SUDO cp "${SRC}/deploy/gx10/health-check.sh"      /etc/systemd/system/health-check.sh
$SUDO chmod 0644 /etc/systemd/system/ai-model-lab.service /etc/systemd/system/health.service /etc/systemd/system/health.timer
$SUDO chmod 0755 /etc/systemd/system/health-check.sh
$SUDO chown "$SERVICE_USER:$SERVICE_USER" /etc/systemd/system/health-check.sh
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now ai-model-lab.service
$SUDO systemctl enable --now health.timer

# --- ownership (the service user owns the tree, incl. the data directory) ----
$SUDO chown -R "$(id -u):$(id -g)" "$INSTALL_ROOT"

log "done. the portal is on http://${PORTAL_HOST}:${PORTAL_PORT}"
log "next: set up Tailscale Serve (deploy/gx10/tailscale-serve.sh), then:"
log "      curl -fsS http://${PORTAL_HOST}:${PORTAL_PORT}/api/health"
