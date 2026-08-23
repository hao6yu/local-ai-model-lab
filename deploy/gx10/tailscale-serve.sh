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
  # Custom domain: if it is not a ts.net subdomain, provision a certificate
  # first. ts.net subdomains get an automatic certificate from Tailscale.
  case "$DOMAIN" in
    *.ts.net) ;;
    *) tailscale cert --bg --hostname "$DOMAIN" 2>/dev/null || true ;;
  esac
  tailscale serve --bg "${PORT}" --https="${DOMAIN}"
else
  # Default: the node's own ts.net name (e.g. <node>.ts.net). Tailscale
  # provisions the certificate automatically; Funnel stays off so only tailnet
  # devices can reach the portal.
  tailscale serve --bg "${PORT}"
fi

echo "current Serve/Funnel state:"
if tailscale serve status 2>/dev/null; then
  :
else
  tailscale status
fi
