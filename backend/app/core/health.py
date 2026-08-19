from collections.abc import Callable
from json import JSONDecodeError

import httpx

from app.core.config import Settings
from app.schemas.health import UpstreamHealth

DEFAULT_TIMEOUT_SECONDS = 3.0
INVALID_MODELS_DETAIL = "upstream returned an invalid /models response"

Probe = Callable[[Settings], UpstreamHealth]


def probe_upstream(
    settings: Settings,
    *,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> UpstreamHealth:
    if not settings.model_api_base:
        return UpstreamHealth(state="unavailable", detail="model endpoint not configured")

    url = settings.model_api_base.rstrip("/") + "/models"
    api_key = settings.model_api_key or None
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        response = client.get(url, headers=headers)
    except httpx.TimeoutException:
        return UpstreamHealth(state="unavailable", detail="model endpoint timed out")
    except httpx.ConnectError:
        return UpstreamHealth(state="unavailable", detail="could not connect to model endpoint")
    except httpx.HTTPError:
        return UpstreamHealth(state="unavailable", detail="model endpoint connection error")
    finally:
        if owns_client:
            client.close()

    if not 200 <= response.status_code < 300:
        if response.status_code in (401, 403):
            return UpstreamHealth(state="unavailable", detail="upstream rejected credentials")
        detail = f"upstream returned HTTP {response.status_code}"
        return UpstreamHealth(state="unavailable", detail=detail)

    try:
        payload = response.json()
    except JSONDecodeError:
        return UpstreamHealth(state="unavailable", detail=INVALID_MODELS_DETAIL)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return UpstreamHealth(state="unavailable", detail=INVALID_MODELS_DETAIL)

    return UpstreamHealth(state="reachable")
