from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.health import probe_upstream
from app.main import create_app
from app.schemas.health import UpstreamHealth
from conftest import MODEL_API_KEY, make_settings

VALID_MODELS_RESPONSE = {"object": "list", "data": [{"id": "qwen3.8-27b"}]}


def _client_for(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _reachable_probe(settings: Settings) -> UpstreamHealth:
    return UpstreamHealth(state="reachable")


def _unavailable_probe(settings: Settings) -> UpstreamHealth:
    return UpstreamHealth(state="unavailable", detail="could not connect to model endpoint")


def test_health_endpoint_reports_reachable_model() -> None:
    client = TestClient(create_app(settings=make_settings(), probe=_reachable_probe))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"portal": "ok", "model": {"state": "reachable", "detail": None}}


def test_health_endpoint_reports_unavailable_model() -> None:
    client = TestClient(create_app(settings=make_settings(), probe=_unavailable_probe))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "portal": "ok",
        "model": {"state": "unavailable", "detail": "could not connect to model endpoint"},
    }


def test_probe_reports_reachable_upstream() -> None:
    client = _client_for(lambda request: httpx.Response(200, json=VALID_MODELS_RESPONSE))
    assert probe_upstream(make_settings(), client=client) == UpstreamHealth(state="reachable")


def test_probe_reports_unconfigured_endpoint() -> None:
    settings = make_settings(model_api_base=None)
    result = probe_upstream(settings)
    assert result.state == "unavailable"
    assert result.detail == "model endpoint not configured"


def test_probe_reports_connect_failure_without_leaking_address_or_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client_for(handler)
    result = probe_upstream(make_settings(), client=client)
    assert result.state == "unavailable"
    assert result.detail == "could not connect to model endpoint"
    detail = result.detail or ""
    assert "http" not in detail
    assert MODEL_API_KEY not in detail


def test_probe_reports_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    client = _client_for(handler)
    result = probe_upstream(make_settings(), client=client)
    assert result.state == "unavailable"
    assert result.detail == "model endpoint timed out"


def test_probe_reports_http_error_status() -> None:
    client = _client_for(lambda request: httpx.Response(503))
    result = probe_upstream(make_settings(), client=client)
    assert result.state == "unavailable"
    assert result.detail == "upstream returned HTTP 503"


def test_probe_reports_redirect_as_unavailable() -> None:
    client = _client_for(lambda request: httpx.Response(302))
    result = probe_upstream(make_settings(), client=client)
    assert result.state == "unavailable"
    assert result.detail == "upstream returned HTTP 302"


def test_probe_reports_html_response_as_unavailable() -> None:
    client = _client_for(lambda request: httpx.Response(200, text="<!doctype html><html></html>"))
    result = probe_upstream(make_settings(), client=client)
    assert result.state == "unavailable"
    assert result.detail == "upstream returned an invalid /models response"


def test_probe_reports_missing_data_list_as_unavailable() -> None:
    client = _client_for(lambda request: httpx.Response(200, json={"object": "list"}))
    result = probe_upstream(make_settings(), client=client)
    assert result.state == "unavailable"
    assert result.detail == "upstream returned an invalid /models response"


def test_probe_reports_rejected_credentials() -> None:
    client = _client_for(lambda request: httpx.Response(401))
    result = probe_upstream(make_settings(), client=client)
    assert result.state == "unavailable"
    assert result.detail == "upstream rejected credentials"


def test_probe_sends_bearer_key_when_configured() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json=VALID_MODELS_RESPONSE)

    client = _client_for(handler)
    probe_upstream(make_settings(model_api_key="sk-test-secret"), client=client)
    assert seen["authorization"] == "Bearer sk-test-secret"


def test_probe_omits_authorization_header_without_key() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json=VALID_MODELS_RESPONSE)

    client = _client_for(handler)
    probe_upstream(make_settings(model_api_key=None), client=client)
    assert seen["authorization"] is None


def test_settings_maps_uppercase_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MODEL_API_BASE",
        "MODEL_API_KEY",
        "MODEL_ID",
        "MODEL_PROFILE_LABEL",
        "MODEL_CONTEXT_WINDOW",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODEL_API_BASE", "http://127.0.0.1:30000/v1")
    monkeypatch.setenv("MODEL_CONTEXT_WINDOW", "131072")

    settings: Settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.model_api_base == "http://127.0.0.1:30000/v1"
    assert settings.model_context_window == 131072
    assert settings.model_id is None
