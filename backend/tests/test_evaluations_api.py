import json
from pathlib import Path

import httpx
from fake_upstream import FakeUpstream, chunk_frame, finish_frame, sse_done, usage_frame
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db.models import EvaluationRun
from app.evaluations import suite_loader
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


def _client(tmp_path: Path, transport: httpx.AsyncBaseTransport | None) -> TestClient:
    settings = make_settings(
        evaluations_dir=str(tmp_path),
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )
    return TestClient(create_app(settings=settings, upstream_transport=transport))


def _seed_run(engine: Engine, name: str, case_hash: str) -> int:
    with sessionmaker(bind=engine)() as session:
        run = EvaluationRun(
            suite_name=name,
            suite_version="1",
            suite_hash=case_hash,
            profile_key="default",
            profile_label="default",
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
