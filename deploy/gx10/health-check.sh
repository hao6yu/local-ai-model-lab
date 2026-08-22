#!/usr/bin/env bash
# Probe the portal health endpoint after reboot and periodically via
# health.timer. Exits 0 only when the portal is up and its upstream model is
# reachable, so the journal records any regression.
set -uo pipefail

PORTAL_URL="${PORTAL_URL:-http://127.0.0.1:8081/api/health}"

exec python3 - "$PORTAL_URL" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read().decode())
except Exception:  # noqa: BLE001 - any transport failure means "unhealthy"
    print("FAILED: portal endpoint unreachable")
    sys.exit(1)

portal = data.get("portal")
model = data.get("model", {})
state = model.get("state") if isinstance(model, dict) else None

if portal != "ok" or state != "reachable":
    print(f"degraded: portal={portal} model.state={state}")
    sys.exit(1)

print("OK: portal ok, model reachable")
sys.exit(0)

PY
