import json

import pytest
from fastapi.testclient import TestClient

from app.core.runtime import is_experimental_label
from app.main import create_app
from conftest import make_settings


def test_runtime_exposes_endpoint_safe_metadata_only() -> None:
    settings = make_settings()
    client = TestClient(create_app(settings=settings))
    body = client.get("/api/runtime").json()
    api_base = settings.model_api_base
    api_key = settings.model_api_key
    assert api_base is not None
    assert api_key is not None
    assert body == {
        "model_id": settings.model_id,
        "profile_label": settings.model_profile_label,
        "context_window": settings.model_context_window,
        "experimental": True,
    }
    text = json.dumps(body)
    assert api_base not in text, "upstream address must not reach the browser"
    assert api_key not in text, "API key must not reach the browser"


def test_runtime_handles_unconfigured_settings() -> None:
    settings = make_settings(
        model_api_base=None,
        model_api_key=None,
        model_id=None,
        model_profile_label=None,
        model_context_window=None,
    )
    client = TestClient(create_app(settings=settings))
    body = client.get("/api/runtime").json()
    assert body == {
        "model_id": None,
        "profile_label": None,
        "context_window": None,
        "experimental": False,
    }


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("community uncensored Qwen3.8-27B NVFP4", True),
        ("official Qwen3.8-27B NVFP4", False),
        ("Experimental DSpark profile", True),
        ("UNCENSORED build", True),
        ("plain official build", False),
        ("", False),
        (None, False),
    ],
)
def test_is_experimental_label(label: str | None, expected: bool) -> None:
    assert is_experimental_label(label) is expected
