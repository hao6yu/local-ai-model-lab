"""Tests for the SPA static serving added in Milestone 6.

The portal is a single process that serves both the API and the built React SPA
from a directory. When that directory is configured the portal serves
``index.html`` for unknown client-side routes and assets from ``assets/``;
unknown ``/api/*`` paths still return a JSON 404 rather than the HTML shell.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from conftest import make_settings


def _build_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>MODEL-LAB-SPA</body></html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('spa')", encoding="utf-8")
    return dist


def _client_with_static(dist: Path) -> TestClient:
    settings = make_settings(database_url="", static_files_dir=str(dist))
    return TestClient(create_app(settings=settings, upstream_transport=None))


def test_root_serves_spa_index(tmp_path: Path) -> None:
    client = _client_with_static(_build_dist(tmp_path))
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "MODEL-LAB-SPA" in response.text


def test_spa_fallback_returns_index_for_client_routes(tmp_path: Path) -> None:
    client = _client_with_static(_build_dist(tmp_path))
    response = client.get("/saved-runs/42")
    assert response.status_code == 200
    assert "MODEL-LAB-SPA" in response.text


def test_asset_is_served_from_build_directory(tmp_path: Path) -> None:
    client = _client_with_static(_build_dist(tmp_path))
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert "spa" in response.text


def test_unknown_api_path_returns_json_404_not_spa(tmp_path: Path) -> None:
    client = _client_with_static(_build_dist(tmp_path))
    response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404
    assert response.json() == {"detail": "no such API: /api/definitely-not-a-route"}


def test_unknown_non_api_path_returns_spa_index(tmp_path: Path) -> None:
    client = _client_with_static(_build_dist(tmp_path))
    response = client.get("/not-a-real-asset")
    assert response.status_code == 200
    assert "MODEL-LAB-SPA" in response.text


def test_no_static_directory_disables_spa_serving(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    settings = make_settings(database_url="", static_files_dir=str(missing))
    client = TestClient(create_app(settings=settings, upstream_transport=None))
    assert client.get("/").status_code == 404
