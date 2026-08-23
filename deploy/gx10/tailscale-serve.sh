#!/usr/bin/env bash
#
# Expose the portal over the tailnet with Tailscale Serve. The portal listens on
# 127.0.0.1:PORT; Serve fronts it with HTTPS. Only tailnet devices can reach it.
#
#   PORTAL_DOMAIN=my-gx10.ts.net   # optional; a random ts.net subdomain is generated if unset
#   PORTAL_PORT=8081
#   sudo ./deploy/gx10/tailscale-serve.sh
#
# Funnel is intentionally NOT enabled: enabling it would publish the portal
# (and therefore the inference proxy) to the public internet. The inference
# endpoints (127.0.0.1:30000/30001/8888) are never registered here, so Serve
# only fronts the portal.
set -euo pipefail

PORT="${PORTAL_PORT:-8081}"

command -v tailscale >/dev/null 2>&1 || { echo "tailscale is not installed on this host" >&2; exit 1; }

# Keep Funnel disabled: only tailnet devices reach the portal. `funnel off` is
# a no-op on Tailscale versions where Serve already implies it.
tailscale funnel off 2>/dev/null || true

DOMAIN="${PORTAL_DOMAIN:-}"

echo "serving the portal on 127.0.0.1:${PORT} (tailnet-only)"
if [ -n "$DOMAIN" ]; then
  # Custom domain: provision a certificate first, then serve the local port on it.
  tailscale cert --bg --hostname "${DOMAIN}" 2>/dev/null || true
  tailscale serve --bg "${PORT}" --https="${DOMAIN}" --cert="${DOMAIN}"
else
  # Default ts.net subdomain: the node's own tailscale hostname (e.g. <node>.ts.net).
  # Tailscale provisions the certificate automatically; keep Funnel off so only
  # tailnet devices can reach the portal.
  tailscale serve --bg "${PORT}"
fi

echo "domain hint: $DOMAIN (when set) or the node's defaults"

echo "current Serve/Funnel state:"
tailscale status --json 2>/dev/null \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("funnel:", d.get("funnel","(not set)")); print("serve:", d.get("serve","(none)"))' 2>/dev/null \
  || tailscale status
