import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fake_upstream import (
    FakeUpstream,
    RecordedRequest,
    chunk_frame,
    finish_frame,
    sse_done,
    usage_frame,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db.models import EvaluationImage, EvaluationResult, EvaluationRun, ManualScore
from app.evaluations import suite_loader
from app.evaluations.orchestrator import _run_image_from_data_url
from app.evaluations.suite_loader import SuiteValidationError
from app.main import create_app
from conftest import make_settings


def _happy_frames() -> list[str]:
    return [
        chunk_frame("Hello"),
        chunk_frame(" world"),
        finish_frame("stop"),
        usage_frame(4, 12),
        sse_done(),
    ]


def _write_suite(suites_dir: Path, name: str, *, disabled: list[int] | None = None) -> Path:
    active = set(disabled or [])
    cases = [
        {"id": "u1", "category": "categorized", "prompt": "hello", "disabled": 1 in active},
        {"id": "u2", "category": "categorized", "prompt": "world"},
        {"id": "u3", "category": "categorized", "prompt": "again", "disabled": True},
    ]
    path = suites_dir / f"{name}.json"
    path.write_text(json.dumps({"version": 1, "cases": cases}), encoding="utf-8")
    return path


def _suite_hash(suites_dir: Path, name: str) -> str:
    raw = (suites_dir / f"{name}.json").read_bytes()
    return suite_loader.hash_bytes(raw)


def _db_engine(tmp_path: Path) -> Engine:
    return create_engine(f"sqlite:///{tmp_path / 'test.db'}")


VISION_PROFILES_JSON = json.dumps(
    [
        {
            "key": "qwen",
            "api_base": "http://127.0.0.1:30001/v1",
            "model_id": "qwen3.8-27b",
            "profile_label": "Qwen3.8-27B",
            "context_window": 131072,
            "supports_vision": True,
        }
    ]
)


def _client(
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport | None = None,
    *,
    extra: dict[str, object] | None = None,
) -> TestClient:
    values: dict[str, object] = {
        "evaluations_dir": str(tmp_path),
        "database_url": f"sqlite:///{tmp_path / 'test.db'}",
    }
    if extra:
        values.update(extra)
    settings = make_settings(**values)
    return TestClient(create_app(settings=settings, upstream_transport=transport))


def _seed_run(
    engine: Engine,
    name: str,
    case_hash: str,
    *,
    profile_key: str = "default",
    profile_label: str = "default",
) -> int:
    with sessionmaker(bind=engine)() as session:
        run = EvaluationRun(
            suite_name=name,
            suite_version="1",
            suite_hash=case_hash,
            profile_key=profile_key,
            profile_label=profile_label,
            state="created",
        )
        session.add(run)
        session.commit()
        return run.id


def _mark_running(engine: Engine, run_id: int) -> None:
    with sessionmaker(bind=engine)() as session:
        run = session.get(EvaluationRun, run_id)
        assert run is not None
        run.state = "running"
        session.commit()


def test_list_suites_reports_every_valid_suite(tmp_path: Path) -> None:
    _write_suite(tmp_path, "alpha")
    _write_suite(tmp_path, "beta", disabled=[1])
    client = _client(tmp_path, None)

    suites = client.get("/api/suites").json()

    assert {item["name"] for item in suites} == {"alpha", "beta"}
    by_name = {item["name"]: item for item in suites}
    assert by_name["alpha"]["case_count"] == 3
    assert by_name["beta"]["case_count"] == 3
    assert by_name["beta"]["version"] == "1"
    for item in suites:
        assert item["hash"] == _suite_hash(tmp_path, item["name"])


def test_list_suites_skips_invalid_and_non_json_files(tmp_path: Path) -> None:
    _write_suite(tmp_path, "good")
    (tmp_path / "broken.json").write_text("{ this is not json", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    client = _client(tmp_path, None)

    suites = client.get("/api/suites").json()

    assert [item["name"] for item in suites] == ["good"]


def test_create_run_records_the_run_snapshot(tmp_path: Path) -> None:
    _write_suite(tmp_path, "demo")
    client = _client(tmp_path, None)

    response = client.post(
        "/api/evaluation-runs", json={"suite_name": "demo", "suite_version": "1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "created"
    assert body["suite_name"] == "demo"
    assert body["suite_version"] == "1"
    assert body["suite_hash"] == _suite_hash(tmp_path, "demo")
    assert body["results"] == []


def test_create_run_requires_a_matching_suite_version(tmp_path: Path) -> None:
    _write_suite(tmp_path, "demo")
    client = _client(tmp_path, None)

    response = client.post(
        "/api/evaluation-runs", json={"suite_name": "demo", "suite_version": "2"}
    )

    assert response.status_code == 400


def test_create_run_404_when_suite_is_missing(tmp_path: Path) -> None:
    client = _client(tmp_path, None)

    response = client.post(
        "/api/evaluation-runs", json={"suite_name": "nope", "suite_version": "1"}
    )

    assert response.status_code == 404


def test_start_missing_run_404(tmp_path: Path) -> None:
    client = _client(tmp_path, None)

    response = client.post("/api/evaluation-runs/999/start")

    assert response.status_code == 404


def test_persistence_required_returns_503_without_engine() -> None:
    from app.main import create_app as _create_app

    settings = make_settings(evaluations_dir="data/suites", database_url="")
    client = TestClient(_create_app(settings=settings, upstream_transport=None))

    response = client.post(
        "/api/evaluation-runs", json={"suite_name": "demo", "suite_version": "1"}
    )

    assert response.status_code == 503


def test_start_missing_suite_marks_run_failed(tmp_path: Path) -> None:
    path = _write_suite(tmp_path, "demo")
    client = _client(tmp_path, FakeUpstream(frames=_happy_frames()).transport)
    run_id = _seed_run(_db_engine(tmp_path), "demo", _suite_hash(tmp_path, "demo"))

    path.unlink()
    response = client.post(f"/api/evaluation-runs/{run_id}/start")

    assert response.status_code == 404
    run = client.get(f"/api/evaluation-runs/{run_id}").json()
    assert run["state"] == "failed"
    assert run["completed_at"] is not None


def test_start_hash_mismatch_returns_409(tmp_path: Path) -> None:
    path = _write_suite(tmp_path, "demo")
    client = _client(tmp_path, FakeUpstream(frames=_happy_frames()).transport)
    run_id = _seed_run(_db_engine(tmp_path), "demo", _suite_hash(tmp_path, "demo"))

    path.write_text(
        json.dumps({"version": 1, "cases": [{"id": "u1", "prompt": "changed"}]}),
        encoding="utf-8",
    )
    response = client.post(f"/api/evaluation-runs/{run_id}/start")

    assert response.status_code == 409


def test_start_conflict_returns_409(tmp_path: Path) -> None:
    _write_suite(tmp_path, "demo")
    client = _client(tmp_path, None)
    case_hash = _suite_hash(tmp_path, "demo")
    created = _seed_run(_db_engine(tmp_path), "demo", case_hash)
    running = _seed_run(_db_engine(tmp_path), "demo", case_hash)
    _mark_running(_db_engine(tmp_path), running)

    response = client.post(f"/api/evaluation-runs/{created}/start")

    assert response.status_code == 409


def test_end_to_end_stream_completes_and_persists(tmp_path: Path) -> None:
    _write_suite(tmp_path, "demo")
    transport = FakeUpstream(frames=_happy_frames()).transport
    client = _client(tmp_path, transport)
    run_id = _seed_run(_db_engine(tmp_path), "demo", _suite_hash(tmp_path, "demo"))

    response = client.post(f"/api/evaluation-runs/{run_id}/start")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: progress" in body
    assert "event: result" in body
    assert "event: done" in body

    run = client.get(f"/api/evaluation-runs/{run_id}").json()
    assert run["state"] == "completed"
    assert run["total_cases"] == 2
    case_ids = [result["case_id"] for result in run["results"]]
    assert case_ids == ["u1", "u2"]
    for result in run["results"]:
        assert result["scores"]["accuracy"] is None


def test_patch_score_persists_and_returns_updated_score(tmp_path: Path) -> None:
    _write_suite(tmp_path, "demo")
    transport = FakeUpstream(frames=_happy_frames()).transport
    client = _client(tmp_path, transport)
    run_id = _seed_run(_db_engine(tmp_path), "demo", _suite_hash(tmp_path, "demo"))
    client.post(f"/api/evaluation-runs/{run_id}/start")

    run = client.get(f"/api/evaluation-runs/{run_id}").json()
    result_id = run["results"][0]["id"]

    response = client.patch(
        f"/api/results/{result_id}/score",
        json={
            "accuracy": 2,
            "completeness": 1,
            "instruction_following": 2,
            "appropriate_judgment": 1,
            "refusal": False,
            "hallucination": True,
            "note": "solid",
        },
    )
    assert response.status_code == 200
    scored = response.json()
    assert scored["accuracy"] == 2
    assert scored["hallucination"] is True
    assert scored["note"] == "solid"

    run = client.get(f"/api/evaluation-runs/{run_id}").json()
    scores = run["results"][0]["scores"]
    assert scores is not None
    assert scores["accuracy"] == 2
    assert scores["hallucination"] is True
    assert scores["note"] == "solid"


def test_patch_missing_score_404(tmp_path: Path) -> None:
    client = _client(tmp_path, None)

    response = client.patch("/api/results/999/score", json={"accuracy": 1})

    assert response.status_code == 404


def test_delete_run_removes_it_and_cascades(tmp_path: Path) -> None:
    _write_suite(tmp_path, "demo")
    client = _client(tmp_path, None)
    engine = _db_engine(tmp_path)
    run_id = _seed_run(engine, "demo", _suite_hash(tmp_path, "demo"))

    with sessionmaker(bind=engine)() as session:
        run = session.get(EvaluationRun, run_id)
        assert run is not None
        run.results.append(
            EvaluationResult(
                case_id="u1",
                index=0,
                category="c",
                prompt="hello",
                state="completed",
                response="hi",
                input_type="text",
            )
        )
        run.results[-1].scores = ManualScore(accuracy=1, instruction_following=True)
        run.images.append(
            EvaluationImage(
                case_id="u1",
                media_type="image/jpeg",
                source="fixture",
                data_url="data:image/jpeg;base64,x",
                bytes=b"\xff\xd8\xff",
            )
        )
        run.state = "completed"
        session.commit()

    response = client.delete(f"/api/evaluation-runs/{run_id}")
    assert response.status_code == 204

    with sessionmaker(bind=engine)() as session:
        assert session.get(EvaluationRun, run_id) is None
        assert session.query(EvaluationResult).filter_by(run_id=run_id).count() == 0
        assert session.query(EvaluationImage).filter_by(run_id=run_id).count() == 0
        assert session.query(ManualScore).count() == 0


def test_delete_missing_run_404(tmp_path: Path) -> None:
    client = _client(tmp_path, None)
    assert client.delete("/api/evaluation-runs/999").status_code == 404


def test_delete_running_run_is_rejected(tmp_path: Path) -> None:
    _write_suite(tmp_path, "demo")
    client = _client(tmp_path, None)
    run_id = _seed_run(_db_engine(tmp_path), "demo", _suite_hash(tmp_path, "demo"))
    _mark_running(_db_engine(tmp_path), run_id)
    assert client.delete(f"/api/evaluation-runs/{run_id}").status_code == 409


def test_delete_503_when_persistence_unavailable(tmp_path: Path) -> None:

    from fastapi.testclient import TestClient

    from app.main import create_app
    from conftest import make_settings

    settings = make_settings(
        evaluations_dir=str(tmp_path),
        database_url="",
    )
    client = TestClient(create_app(settings=settings))
    assert client.delete("/api/evaluation-runs/1").status_code == 503


def test_list_suite_cases_returns_enabled_cases_only(tmp_path: Path) -> None:
    _write_suite(tmp_path, "alpha")
    client = _client(tmp_path, None)

    cases = client.get("/api/suites/alpha/cases").json()

    assert [c["id"] for c in cases] == ["u1", "u2"]
    assert all(c["input_type"] == "text" for c in cases)
    assert all(c["case_type"] is None for c in cases)
    assert all(c["disabled"] is False for c in cases)
    caption = next(c for c in cases if c["id"] == "u1")
    assert caption["category"] == "categorized"
    assert caption["prompt"] == "hello"


def test_list_suite_cases_404_for_missing_suite(tmp_path: Path) -> None:
    client = _client(tmp_path, None)

    response = client.get("/api/suites/nope/cases")

    assert response.status_code == 404


def test_list_suite_cases_reports_input_type_and_case_type(tmp_path: Path) -> None:
    (tmp_path / "gallery.json").write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    {
                        "id": "caption",
                        "category": "caption",
                        "prompt": "Describe",
                        "input_type": "image",
                        "case_type": "transcribe",
                        "expected_transcription": "caption text",
                    },
                    {
                        "id": "explain",
                        "category": "explain",
                        "prompt": "Interpret",
                        "input_type": "image",
                        "case_type": "interpret",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    client = _client(tmp_path, None)

    cases = client.get("/api/suites/gallery/cases").json()
    by_id = {c["id"]: c for c in cases}

    assert by_id["caption"]["input_type"] == "image"
    assert by_id["caption"]["case_type"] == "transcribe"
    assert by_id["explain"]["input_type"] == "image"
    assert by_id["explain"]["case_type"] == "interpret"


def _png_data_url() -> str:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"


def _write_image_suite(suites_dir: Path, name: str, *, fixture: bool = False) -> None:
    case: dict[str, object] = {
        "id": "img1",
        "prompt": "Describe the image",
        "input_type": "image",
        "case_type": "transcribe",
        "expected_transcription": "sample text",
    }
    if fixture:
        case["image"] = {"file": f"{name}-fixture.png"}
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (4, 4), (0, 255, 0)).save(buf, format="PNG")
        (suites_dir / f"{name}-fixture.png").write_bytes(buf.getvalue())
    (suites_dir / f"{name}.json").write_text(
        json.dumps({"version": 1, "cases": [case]}), encoding="utf-8"
    )


def _vision_client(tmp_path: Path) -> TestClient:
    settings = make_settings(
        evaluations_dir=str(tmp_path),
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        model_profiles_json=VISION_PROFILES_JSON,
        default_model_profile="qwen",
    )
    return TestClient(create_app(settings=settings, upstream_transport=None))


# ── _run_image_from_data_url unit tests ──────────────────────────────────────


def test_run_image_from_data_url_rejects_non_data_url() -> None:
    with pytest.raises(HTTPException) as excinfo:
        _run_image_from_data_url("not-a-data-url")
    assert excinfo.value.status_code == 400
    assert "data URL" in excinfo.value.detail


def test_run_image_from_data_url_rejects_non_base64_transport() -> None:
    with pytest.raises(HTTPException) as excinfo:
        _run_image_from_data_url("data:image/png;charset=utf8,abc")
    assert excinfo.value.status_code == 400
    assert "base64" in excinfo.value.detail


def test_run_image_from_data_url_rejects_non_image_media_type() -> None:
    with pytest.raises(HTTPException) as excinfo:
        _run_image_from_data_url("data:text/plain;base64,QQQQ")
    assert excinfo.value.status_code == 400
    assert "image media type" in excinfo.value.detail


def test_run_image_from_data_url_rejects_bad_base64() -> None:
    # "QQQQQ" → 5 data chars + auto-pad → "QQQQQ===" → invalid base64
    with pytest.raises(HTTPException) as excinfo:
        _run_image_from_data_url("data:image/png;base64,QQQQQ")
    assert excinfo.value.status_code == 400
    assert "base64" in excinfo.value.detail


def test_run_image_from_data_url_returns_png_bytes() -> None:
    raw = _run_image_from_data_url(_png_data_url())
    assert raw[:4] == b"\x89PNG"


# ── integration tests for the image evaluation path ──────────────────────────


def test_create_run_image_vision_mismatch_400(tmp_path: Path) -> None:
    _write_image_suite(tmp_path, "gallery")
    default_client = _client(tmp_path, None)

    response = default_client.post(
        "/api/evaluation-runs",
        json={
            "suite_name": "gallery",
            "suite_version": "1",
            "images": [{"case_id": "img1", "data_url": _png_data_url()}],
        },
    )

    assert response.status_code == 400
    assert "cannot process images" in response.json()["detail"]


def test_create_run_image_no_image_400(tmp_path: Path) -> None:
    _write_image_suite(tmp_path, "gallery")
    client = _vision_client(tmp_path)

    response = client.post(
        "/api/evaluation-runs",
        json={"suite_name": "gallery", "suite_version": "1", "images": []},
    )

    assert response.status_code == 400
    assert "no image" in response.json()["detail"]


def test_create_run_stores_attached_image(tmp_path: Path) -> None:
    _write_image_suite(tmp_path, "gallery")
    client = _vision_client(tmp_path)

    response = client.post(
        "/api/evaluation-runs",
        json={
            "suite_name": "gallery",
            "suite_version": "1",
            "images": [{"case_id": "img1", "data_url": _png_data_url()}],
        },
    )

    assert response.status_code == 200
    run_id = response.json()["id"]
    engine = _db_engine(tmp_path)
    with sessionmaker(bind=engine)() as session:
        image = session.query(EvaluationImage).filter_by(run_id=run_id).one()
        assert image.case_id == "img1"
        assert image.source == "attachment"
        assert image.media_type == "image/jpeg"
        assert len(image.bytes) > 0


def test_create_run_image_fixture_fallback(tmp_path: Path) -> None:
    _write_image_suite(tmp_path, "gallery", fixture=True)
    client = _vision_client(tmp_path)

    response = client.post(
        "/api/evaluation-runs",
        json={"suite_name": "gallery", "suite_version": "1"},
    )

    assert response.status_code == 200
    run_id = response.json()["id"]
    engine = _db_engine(tmp_path)
    with sessionmaker(bind=engine)() as session:
        image = session.query(EvaluationImage).filter_by(run_id=run_id).one()
        assert image.source == "fixture"
        assert image.case_id == "img1"


def test_list_suite_cases_reports_has_fixture(tmp_path: Path) -> None:
    _write_image_suite(tmp_path, "gallery", fixture=True)
    client = _client(tmp_path, None)

    cases = client.get("/api/suites/gallery/cases").json()
    by_id = {c["id"]: c for c in cases}

    assert by_id["img1"]["has_fixture"] is True
    assert by_id["img1"]["input_type"] == "image"


def _write_cases(suites_dir: Path, name: str, cases: list[dict[str, object]]) -> Path:
    path = suites_dir / f"{name}.json"
    path.write_text(json.dumps({"version": 1, "cases": cases}), encoding="utf-8")
    return path


def _message_contents(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw: Any = body.get("messages", [])
    if not isinstance(raw, list):
        return []
    return [item if isinstance(item, dict) else {} for item in raw]


def _image_url_parts(body: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for message in _message_contents(body):
        content: object = message.get("content")
        if isinstance(content, list):
            parts.extend(
                part["image_url"]["url"]
                for part in content
                if isinstance(part, dict) and part.get("type") == "image_url"
            )
    return parts


def _vision_client_with_transport(
    tmp_path: Path, transport: httpx.AsyncBaseTransport | None
) -> TestClient:
    return _client(
        tmp_path,
        transport,
        extra={"model_profiles_json": VISION_PROFILES_JSON, "default_model_profile": "qwen"},
    )


# ── item 5: exactly one attachment per image case ─────────────────────────────

IMAGE_CASES: list[dict[str, object]] = [
    {
        "id": "img1",
        "prompt": "Describe",
        "input_type": "image",
        "case_type": "transcribe",
        "expected_transcription": "sample text",
    },
    {"id": "txt1", "prompt": "plain text"},
    {
        "id": "img2",
        "prompt": "later",
        "input_type": "image",
        "case_type": "interpret",
        "disabled": True,
    },
]


def test_duplicate_attachment_for_same_case_is_rejected(tmp_path: Path) -> None:
    _write_cases(tmp_path, "gallery", IMAGE_CASES)
    client = _vision_client(tmp_path)
    response = client.post(
        "/api/evaluation-runs",
        json={
            "suite_name": "gallery",
            "suite_version": "1",
            "images": [
                {"case_id": "img1", "data_url": _png_data_url()},
                {"case_id": "img1", "data_url": _png_data_url()},
            ],
        },
    )
    assert response.status_code == 400
    assert "more than one" in response.json()["detail"]


def test_attachment_for_unknown_case_is_rejected(tmp_path: Path) -> None:
    _write_cases(tmp_path, "gallery", IMAGE_CASES)
    client = _vision_client(tmp_path)
    response = client.post(
        "/api/evaluation-runs",
        json={
            "suite_name": "gallery",
            "suite_version": "1",
            "images": [{"case_id": "missing", "data_url": _png_data_url()}],
        },
    )
    assert response.status_code == 400
    assert "no case 'missing'" in response.json()["detail"]


def test_attachment_to_text_case_is_rejected(tmp_path: Path) -> None:
    _write_cases(tmp_path, "gallery", IMAGE_CASES)
    client = _vision_client(tmp_path)
    response = client.post(
        "/api/evaluation-runs",
        json={
            "suite_name": "gallery",
            "suite_version": "1",
            "images": [{"case_id": "txt1", "data_url": _png_data_url()}],
        },
    )
    assert response.status_code == 400
    assert "text case" in response.json()["detail"]


def test_attachment_to_disabled_case_is_rejected(tmp_path: Path) -> None:
    _write_cases(tmp_path, "gallery", IMAGE_CASES)
    client = _vision_client(tmp_path)
    response = client.post(
        "/api/evaluation-runs",
        json={
            "suite_name": "gallery",
            "suite_version": "1",
            "images": [{"case_id": "img2", "data_url": _png_data_url()}],
        },
    )
    assert response.status_code == 400
    assert "disabled" in response.json()["detail"]


# ── item 6: run modality is derived from the loaded suite ──────────────────────


def test_image_run_derives_image_modality_even_when_client_sends_text(tmp_path: Path) -> None:
    _write_cases(tmp_path, "gallery", IMAGE_CASES)
    client = _vision_client(tmp_path)
    response = client.post(
        "/api/evaluation-runs",
        json={
            "suite_name": "gallery",
            "suite_version": "1",
            "modality": "text",
            "images": [{"case_id": "img1", "data_url": _png_data_url()}],
        },
    )
    assert response.status_code == 200
    # gallery has one enabled image case and one enabled text case, so the
    # server derives "mixed" rather than trusting the client's "text".
    assert response.json()["modality"] == "mixed"


def test_text_run_stays_text_even_when_client_sends_image(tmp_path: Path) -> None:
    _write_suite(tmp_path, "alpha")
    client = _vision_client(tmp_path)
    response = client.post(
        "/api/evaluation-runs",
        json={"suite_name": "alpha", "suite_version": "1", "modality": "image"},
    )
    assert response.status_code == 200
    assert response.json()["modality"] == "text"


def test_image_only_suite_derives_image_modality(tmp_path: Path) -> None:
    _write_cases(
        tmp_path,
        "onlyimage",
        [
            {
                "id": "img1",
                "prompt": "describe",
                "input_type": "image",
                "case_type": "transcribe",
                "expected_transcription": "sample",
            },
        ],
    )
    client = _vision_client(tmp_path)
    response = client.post(
        "/api/evaluation-runs",
        json={
            "suite_name": "onlyimage",
            "suite_version": "1",
            "modality": "text",
            "images": [{"case_id": "img1", "data_url": _png_data_url()}],
        },
    )
    assert response.status_code == 200
    assert response.json()["modality"] == "image"


def test_suite_with_duplicate_case_ids_is_rejected_on_run_creation(tmp_path: Path) -> None:
    _write_cases(
        tmp_path,
        "dupes",
        [
            {"id": "dup", "prompt": "first"},
            {"id": "dup", "prompt": "second"},
        ],
    )
    client = _client(tmp_path, None)
    response = client.post(
        "/api/evaluation-runs",
        json={"suite_name": "dupes", "suite_version": "1"},
    )
    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()


def test_suite_with_duplicate_image_case_ids_cannot_create_a_run(tmp_path: Path) -> None:
    _write_cases(
        tmp_path,
        "dupimage",
        [
            {
                "id": "img1",
                "prompt": "a",
                "input_type": "image",
                "case_type": "transcribe",
                "expected_transcription": "a",
            },
            {
                "id": "img1",
                "prompt": "b",
                "input_type": "image",
                "case_type": "interpret",
            },
        ],
    )
    client = _vision_client(tmp_path)
    response = client.post(
        "/api/evaluation-runs",
        json={"suite_name": "dupimage", "suite_version": "1"},
    )
    assert response.status_code == 400


def test_invalid_suite_is_rejected_on_run_creation(tmp_path: Path) -> None:
    _write_cases(
        tmp_path,
        "broken",
        [
            {"id": "img1", "prompt": "describe", "input_type": "image", "case_type": "image"},
        ],
    )
    client = _client(tmp_path, None)
    response = client.post(
        "/api/evaluation-runs",
        json={"suite_name": "broken", "suite_version": "1"},
    )
    assert response.status_code == 400


def test_invalid_image_cases_are_excluded_from_suite_listing(tmp_path: Path) -> None:
    _write_cases(
        tmp_path,
        "bad_type",
        [
            {"id": "img1", "prompt": "p", "input_type": "image", "case_type": "image"},
        ],
    )
    _write_cases(
        tmp_path,
        "no_type",
        [
            {"id": "img1", "prompt": "p", "input_type": "image"},
        ],
    )
    _write_cases(
        tmp_path,
        "bad_text",
        [
            {"id": "txt1", "prompt": "p", "image": {"file": "x.png"}},
        ],
    )
    client = _client(tmp_path, None)
    listed = {item["name"] for item in client.get("/api/suites").json()}
    assert listed == set()
    assert client.get("/api/suites/bad_type/cases").status_code == 404
    assert client.get("/api/suites/no_type/cases").status_code == 404
    assert client.get("/api/suites/bad_text/cases").status_code == 404


def test_image_run_sends_jpeg_data_url(tmp_path: Path) -> None:
    _write_cases(tmp_path, "gallery", IMAGE_CASES)
    upstream = FakeUpstream(frames=_happy_frames())
    client = _vision_client_with_transport(tmp_path, upstream.transport)
    created = client.post(
        "/api/evaluation-runs",
        json={
            "suite_name": "gallery",
            "suite_version": "1",
            "images": [{"case_id": "img1", "data_url": _png_data_url()}],
        },
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["id"]

    client.post(f"/api/evaluation-runs/{run_id}/start")

    requests = [req for req in upstream.state.requests if req.body is not None]
    # gallery has two enabled cases: img1 (image) and txt1 (text).
    assert requests, "expected at least one upstream request"

    image_requests: list[RecordedRequest] = []
    text_requests: list[RecordedRequest] = []
    for req in requests:
        body = req.body
        assert body is not None
        if _image_url_parts(body):
            image_requests.append(req)
        else:
            text_requests.append(req)
    assert image_requests, "the image case must embed a payload in its message content"
    assert text_requests, "the text case must not embed a payload"

    for req in image_requests:
        body = req.body
        assert body is not None
        urls = _image_url_parts(body)
        assert len(urls) == 1, urls
        url = urls[0]
        assert isinstance(url, str), url
        assert url.startswith("data:image/jpeg;base64,"), url
        assert url != _png_data_url(), "accepted formats must be normalized to JPEG upstream"
        # The prompt text is preserved alongside the embedded image.
        content = _message_contents(body)[-1].get("content")
        assert isinstance(content, list)
        text_parts = [part["text"] for part in content if part.get("type") == "text"]
        assert "Describe" in text_parts

    for req in text_requests:
        body = req.body
        assert body is not None
        for message in _message_contents(body):
            content = message.get("content")
            assert not isinstance(content, list), "a text case must keep a plain string payload"


def test_text_run_payload_carries_no_image(tmp_path: Path) -> None:
    _write_suite(tmp_path, "alpha")
    upstream = FakeUpstream(frames=_happy_frames())
    client = _client(tmp_path, upstream.transport)
    run_id = _seed_run(_db_engine(tmp_path), "alpha", _suite_hash(tmp_path, "alpha"))
    client.post(f"/api/evaluation-runs/{run_id}/start")

    requests = [req for req in upstream.state.requests if req.body is not None]
    assert requests, "text cases must still produce an upstream request"
    for req in requests:
        body = req.body
        assert body is not None
        for message in _message_contents(body):
            content = message.get("content")
            assert not isinstance(content, list), "a text case must keep a plain string payload"


# ── item 4 / U13: the shipped vision suite is actually runnable ────────────────

_SHIPPED_SUITES = Path(__file__).resolve().parents[2] / "data" / "suites"


def _vision_client_with_suite(tmp_path: Path, suites_dir: Path) -> TestClient:
    settings = make_settings(
        evaluations_dir=str(suites_dir),
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        model_profiles_json=VISION_PROFILES_JSON,
        default_model_profile="qwen",
    )
    return TestClient(create_app(settings=settings, upstream_transport=None))


def _find_case(cases: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    return next(c for c in cases if c["id"] == case_id)


def test_shipped_vision_suite_loads_enabled_u13_with_known_transcription() -> None:
    loaded = suite_loader.load_suite("uncensored-behavior-v1", str(_SHIPPED_SUITES))

    u13 = next(c for c in loaded.all_cases() if c.id == "U13")
    assert u13.disabled is False
    assert u13.is_image is True
    assert u13.case_type == "transcribe"
    assert u13.expected_transcription == "LOCAL AI MODEL LAB"
    assert u13.image is not None

    u13b = next(c for c in loaded.all_cases() if c.id == "U13B")
    assert u13b.disabled is False
    assert u13b.is_image is True
    assert u13b.case_type == "interpret"

    enabled_ids = {c.id for c in loaded.enabled_image_cases()}
    assert enabled_ids == {"U13", "U13B"}


def test_shipped_vision_fixture_file_is_a_readable_png(tmp_path: Path) -> None:
    from app.image import validation

    fixture = _SHIPPED_SUITES / "fixtures" / "u13-transcription.png"
    assert fixture.exists()
    raw = fixture.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    prepared = validation.prepare_image(raw)
    assert prepared.media_type in ("image/jpeg", "image/png")
    assert len(prepared.bytes) > 0


def test_list_suite_cases_reports_shipped_u13_as_image_case(tmp_path: Path) -> None:
    client = _client(tmp_path, None, extra={"evaluations_dir": str(_SHIPPED_SUITES)})

    cases = client.get("/api/suites/uncensored-behavior-v1/cases").json()
    u13 = _find_case(cases, "U13")

    assert u13["input_type"] == "image"
    assert u13["case_type"] == "transcribe"
    assert u13["expected_transcription"] == "LOCAL AI MODEL LAB"
    assert u13["disabled"] is False
    assert u13["has_fixture"] is True


def test_shipped_vision_run_stores_fixture_image(tmp_path: Path) -> None:
    client = _vision_client_with_suite(tmp_path, _SHIPPED_SUITES)

    response = client.post(
        "/api/evaluation-runs",
        json={"suite_name": "uncensored-behavior-v1", "suite_version": "2"},
    )
    assert response.status_code == 200

    run_id = response.json()["id"]
    engine = _db_engine(tmp_path)
    with sessionmaker(bind=engine)() as session:
        images = (
            session.query(EvaluationImage)
            .filter_by(run_id=run_id)
            .order_by(EvaluationImage.case_id)
            .all()
        )
        image_ids = {image.case_id for image in images}
        assert image_ids == {"U13", "U13B"}
        for image in images:
            assert image.source == "fixture"
            assert len(image.bytes) > 0

    with sessionmaker(bind=engine)() as session:
        run = session.get(EvaluationRun, run_id)
        assert run is not None
        # The shipped suite mixes text cases with enabled image cases, so the
        # server records "mixed" rather than "image".
        assert run.modality == "mixed"
        assert len(run.results) == 0


def test_transcribe_case_without_known_transcription_is_rejected(tmp_path: Path) -> None:
    suite = tmp_path / "broken.json"
    suite.write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    {
                        "id": "bad",
                        "category": "categorized",
                        "prompt": "describe the picture",
                        "input_type": "image",
                        "case_type": "transcribe",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SuiteValidationError) as excinfo:
        suite_loader.load_suite("broken", str(tmp_path))

    message = str(excinfo.value)
    assert "bad" in message
    assert "expected_transcription" in message
