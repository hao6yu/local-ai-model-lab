#!/usr/bin/env bash
#
# Expose the portal over the tailnet with Tailscale Serve. The portal listens on
# 127.0.0.1:PORT; Serve fronts it with HTTPS. Only tailnet devices can reach it.
#
#   PORTAL_DOMAIN=my-gx10.ts.net   # optional; a ts.net subdomain is used if unset
#   PORTAL_PORT=8081
#   sudo ./deploy/gx10/tailscale-serve.sh
#
# Funnel is intentionally NOT enabled: enabling it would publish the portal (and
# therefore the inference proxy) to the public internet. The inference endpoints
# (127.0.0.1:30000/30001/8888) are never registered here, so Serve only fronts
# the portal.
set -euo pipefail

PORT="${PORTAL_PORT:-8081}"

if ! command -v tailscale >/dev/null 2>&1; then
  echo "install: tailscale is not installed on this host" >&2
  exit 1
fi

# Keep Funnel disabled: only tailnet devices reach the portal.
tailscale funnel off

if [ -n "${PORTAL_DOMAIN:-}" ]; then
  echo "install: serving https://${PORTAL_DOMAIN} (tailnet) -> 127.0.0.1:${PORT}"
  tailscale serve --bg set --http="${PORT}" --https="${PORTAL_DOMAIN}" --cert="${PORTAL_DOMAIN}"
else
  sub="$(tailscale host-id 2>/dev/null || echo aml)"
  DOMAIN="aml-${sub}.ts.net"
  echo "install: serving https://${DOMAIN} (tailnet) -> 127.0.0.1:${PORT}"
  tailscale serve --bg set --http="${PORT}" --https="${DOMAIN}"
fi

echo "install: current Serve/Funnel state:"
tailscale status --json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print("funnel:", d.get("funnel")); print("serve:", d.get("serve"))' 2>/dev/null \
  || tailscale status
