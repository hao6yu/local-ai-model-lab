import json
from pathlib import Path

import httpx
import pytest
from fake_upstream import FakeUpstream, chunk_frame, finish_frame, sse_done, usage_frame
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db.models import EvaluationRun
from app.evaluations import suite_loader
from app.evaluations.schemas import EvalResultWithScores, EvalScorePayload
from app.main import create_app
from conftest import make_settings


def _happy_frames() -> list[str]:
    return [
        chunk_frame("Answer"),
        finish_frame("stop"),
        usage_frame(4, 12),
        sse_done(),
    ]


def _write_suite(suites_dir: Path, name: str, *, case_ids: list[str] | None = None) -> Path:
    ids = case_ids or ["c1", "c2", "c3"]
    cases = [
        {
            "id": idx,
            "category": "sensitive" if idx == "c1" else "general",
            "prompt": f"question {idx}",
        }
        for idx in ids
    ]
    path = suites_dir / f"{name}.json"
    path.write_text(json.dumps({"version": 1, "cases": cases}), encoding="utf-8")
    return path


def _hash_for(suites_dir: Path, name: str) -> str:
    return suite_loader.load_suite(name, str(suites_dir)).hash


def _engine(tmp_path: Path) -> Engine:
    return create_engine(f"sqlite:///{tmp_path / 'test.db'}")


def _client(tmp_path: Path, transport: httpx.AsyncBaseTransport | None) -> TestClient:
    settings = make_settings(
        evaluations_dir=str(tmp_path),
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )
    return TestClient(create_app(settings=settings, upstream_transport=transport))


def _seed(
    tmp_path: Path,
    name: str,
    *,
    profile_label: str,
    version: str = "1",
    hash_override: str | None = None,
) -> int:
    engine = _engine(tmp_path)
    with sessionmaker(bind=engine)() as session:
        run = EvaluationRun(
            suite_name=name,
            suite_version=version,
            suite_hash=hash_override if hash_override is not None else _hash_for(tmp_path, name),
            profile_key="default",
            profile_label=profile_label,
            state="created",
        )
        session.add(run)
        session.commit()
        return run.id


def _patch_score(client: TestClient, result_id: int, accuracy: int, **fields: object) -> None:
    body: dict[str, object] = {
        "accuracy": accuracy,
        "completeness": accuracy,
        "instruction_following": accuracy,
    }
    body.update(fields)
    client.patch(
        f"/api/results/{result_id}/score",
        json=body,
    )


def _result(
    case_id: str, prompt: str, *, score: EvalScorePayload | None = None
) -> EvalResultWithScores:
    return EvalResultWithScores(
        id=1,
        case_id=case_id,
        index=1,
        category="sensitive",
        prompt=prompt,
        response="No, I cannot help with that.",
        finish_reason="stop",
        state="completed",
        scores=score,
    )


def _two_completed_runs(
    tmp_path: Path, transport: httpx.AsyncBaseTransport, left_label: str, right_label: str
) -> tuple[TestClient, int, int]:
    _write_suite(tmp_path, "demo")
    client = _client(tmp_path, transport)
    left_id = _seed(tmp_path, "demo", profile_label=left_label)
    right_id = _seed(tmp_path, "demo", profile_label=right_label)
    client.post(f"/api/evaluation-runs/{left_id}/start")
    client.post(f"/api/evaluation-runs/{right_id}/start")
    return client, left_id, right_id


def _left_result_ids(client: TestClient, run_id: int) -> list[int]:
    run = client.get(f"/api/evaluation-runs/{run_id}").json()
    return [result["id"] for result in run["results"]]


def test_comparison_returns_both_runs_with_summaries(tmp_path: Path) -> None:
    client, left_id, right_id = _two_completed_runs(
        tmp_path, FakeUpstream(frames=_happy_frames()).transport, "Ornith profile", "Qwen profile"
    )
    _patch_score(client, _left_result_ids(client, left_id)[0], 2)
    _patch_score(client, _left_result_ids(client, left_id)[1], 1)

    response = client.get("/api/comparisons", params={"left": left_id, "right": right_id})

    assert response.status_code == 200
    body = response.json()
    assert body["left"]["profile_label"] == "Ornith profile"
    assert body["right"]["profile_label"] == "Qwen profile"
    assert body["left"]["suite_name"] == body["right"]["suite_name"] == "demo"
    assert len(body["left"]["results"]) == 3
    assert len(body["right"]["results"]) == 3
    summaries = body["summaries"]
    assert summaries["left"]["overall"]["scored_count"] > 0
    assert summaries["left"]["overall"]["total_count"] == 3
    assert summaries["right"]["overall"]["scored_count"] == 0


def test_comparison_400_when_runs_are_incompatible(tmp_path: Path) -> None:
    _write_suite(tmp_path, "demo")
    _write_suite(tmp_path, "other")
    transport = FakeUpstream(frames=_happy_frames()).transport
    client = _client(tmp_path, transport)
    left_id = _seed(tmp_path, "demo", profile_label="Ornith profile")
    right_id = _seed(tmp_path, "other", profile_label="Qwen profile")
    client.post(f"/api/evaluation-runs/{left_id}/start")
    client.post(f"/api/evaluation-runs/{right_id}/start")

    response = client.get("/api/comparisons", params={"left": left_id, "right": right_id})
    assert response.status_code == 400


def test_comparison_400_for_suite_version_mismatch(tmp_path: Path) -> None:
    transport = FakeUpstream(frames=_happy_frames()).transport
    client = _client(tmp_path, transport)
    _write_suite(tmp_path, "demo")
    left_id = _seed(tmp_path, "demo", profile_label="Ornith profile")
    right_id = _seed(
        tmp_path,
        "demo",
        profile_label="Qwen profile",
        version="2",
        hash_override=_hash_for(tmp_path, "demo"),
    )
    client.post(f"/api/evaluation-runs/{left_id}/start")
    client.post(f"/api/evaluation-runs/{right_id}/start")

    response = client.get("/api/comparisons", params={"left": left_id, "right": right_id})
    assert response.status_code == 400
    assert "version" in response.json()["detail"].lower()


def test_comparison_400_for_matching_run_id(tmp_path: Path) -> None:
    client, left_id, _right_id = _two_completed_runs(
        tmp_path, FakeUpstream(frames=_happy_frames()).transport, "Ornith profile", "Qwen profile"
    )
    response = client.get("/api/comparisons", params={"left": left_id, "right": left_id})
    assert response.status_code == 400


def test_comparison_404_for_missing_run(tmp_path: Path) -> None:
    client, left_id, _right_id = _two_completed_runs(
        tmp_path, FakeUpstream(frames=_happy_frames()).transport, "Ornith profile", "Qwen profile"
    )
    response = client.get("/api/comparisons", params={"left": left_id, "right": 999})
    assert response.status_code == 404


def test_comparison_export_returns_markdown(tmp_path: Path) -> None:
    client, left_id, right_id = _two_completed_runs(
        tmp_path, FakeUpstream(frames=_happy_frames()).transport, "Ornith profile", "Qwen profile"
    )

    response = client.get(
        "/api/comparisons/export", params={"left": left_id, "right": right_id, "format": "markdown"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "Ornith profile" in response.text
    assert "Qwen profile" in response.text
    assert "Suite: demo" in response.text
    assert "## Results" in response.text
    assert "descriptive, not significance" in response.text


def test_comparison_export_returns_json(tmp_path: Path) -> None:
    client, left_id, right_id = _two_completed_runs(
        tmp_path, FakeUpstream(frames=_happy_frames()).transport, "Ornith profile", "Qwen profile"
    )

    response = client.get(
        "/api/comparisons/export", params={"left": left_id, "right": right_id, "format": "json"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = json.loads(response.text)
    assert payload["left"]["profile_label"] == "Ornith profile"
    assert payload["right"]["profile_label"] == "Qwen profile"
    assert payload["left"]["suite_name"] == "demo"
    assert "overall" in payload["summaries"]["left"]
    assert "overall" in payload["summaries"]["right"]


def test_comparison_export_rejects_incompatible(tmp_path: Path) -> None:
    client, left_id, _right_id = _two_completed_runs(
        tmp_path, FakeUpstream(frames=_happy_frames()).transport, "Ornith profile", "Qwen profile"
    )
    response = client.get(
        "/api/comparisons/export", params={"left": left_id, "right": left_id, "format": "json"}
    )
    assert response.status_code == 400


def test_comparison_400_when_run_not_finished(tmp_path: Path) -> None:
    _write_suite(tmp_path, "demo")
    transport = FakeUpstream(frames=_happy_frames()).transport
    client = _client(tmp_path, transport)
    started_id = _seed(tmp_path, "demo", profile_label="Ornith profile")
    client.post(f"/api/evaluation-runs/{started_id}/start")
    not_started_id = _seed(tmp_path, "demo", profile_label="Qwen profile")

    response = client.get("/api/comparisons", params={"left": started_id, "right": not_started_id})
    assert response.status_code == 400
    assert "not finished" in response.json()["detail"].lower()


def test_comparison_rejects_prompt_mismatch(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from app.evaluations.comparison import ComparisonError, assert_compatible
    from app.evaluations.schemas import EvalResultWithScores, EvalRunDetail

    created = datetime(2024, 1, 1, tzinfo=UTC)

    def make(run_id: int, results: list[EvalResultWithScores]) -> EvalRunDetail:
        return EvalRunDetail(
            id=run_id,
            suite_name="demo",
            suite_version="1",
            suite_hash="h",
            profile_label="profile",
            created_at=created,
            state="completed",
            results=results,
        )

    with pytest.raises(ComparisonError, match="prompt"):
        assert_compatible(
            make(1, [_result(case_id="c1", prompt="same prompt")]),
            make(2, [_result(case_id="c1", prompt="different prompt")]),
        )


def test_comparison_export_includes_prompt_note_and_flags(tmp_path: Path) -> None:
    client, left_id, right_id = _two_completed_runs(
        tmp_path, FakeUpstream(frames=_happy_frames()).transport, "Ornith profile", "Qwen profile"
    )
    _patch_score(
        client,
        _left_result_ids(client, left_id)[0],
        2,
        note="Clear refusal",
        refusal=True,
        hallucination=False,
    )

    response = client.get(
        "/api/comparisons/export",
        params={"left": left_id, "right": right_id, "format": "markdown"},
    )

    assert response.status_code == 200
    assert "question c1" in response.text
    assert "Clear refusal" in response.text


def test_comparison_includes_error_results_when_run_is_failed(tmp_path: Path) -> None:
    _write_suite(tmp_path, "demo")
    ok_client = _client(
        tmp_path,
        FakeUpstream(frames=_happy_frames()).transport,
    )
    err_client = _client(
        tmp_path,
        FakeUpstream(status=400, error_response=b'{"error": {"message": "boom"}}').transport,
    )
    ok_id = _seed(tmp_path, "demo", profile_label="Ornith profile")
    err_id = _seed(tmp_path, "demo", profile_label="Qwen profile")

    ok_client.post(f"/api/evaluation-runs/{ok_id}/start")
    for result_id in _left_result_ids(ok_client, ok_id):
        _patch_score(ok_client, result_id, 2)

    err_client.post(f"/api/evaluation-runs/{err_id}/start")

    with sessionmaker(bind=_engine(tmp_path))() as session:
        refreshed_run = session.get(EvaluationRun, err_id)
        assert refreshed_run is not None
        assert refreshed_run.state == "failed"
        assert any(result.state == "failed" for result in refreshed_run.results)

    response = ok_client.get("/api/comparisons", params={"left": ok_id, "right": err_id})
    assert response.status_code == 200
    body = response.json()
    assert body["right"]["state"] == "failed"
    error_results = [result for result in body["right"]["results"] if result.get("error")]
    assert error_results
    for error_result in error_results:
        assert error_result["error"]["message"]

    export = ok_client.get(
        "/api/comparisons/export",
        params={"left": ok_id, "right": err_id, "format": "markdown"},
    )
    assert export.status_code == 200
    assert "error:" in export.text


def test_assert_compatible_accepts_failed_run_with_error_result() -> None:
    from datetime import UTC, datetime

    from app.evaluations.comparison import (
        assert_compatible,
        build_comparison_response,
        render_comparison_json,
        render_comparison_markdown,
    )
    from app.evaluations.schemas import EvalErrorPayload, EvalRunDetail

    created = datetime(2024, 1, 1, tzinfo=UTC)

    def make(run_id: int, state: str, results: list[EvalResultWithScores]) -> EvalRunDetail:
        return EvalRunDetail(
            id=run_id,
            suite_name="demo",
            suite_version="1",
            suite_hash="h",
            profile_label="profile",
            created_at=created,
            state=state,
            results=results,
        )

    completed = make(
        1,
        "completed",
        [
            _result(case_id="c1", prompt="question c1"),
            _result(case_id="c2", prompt="question c2"),
        ],
    )
    failed = make(
        2,
        "failed",
        [
            _result(case_id="c1", prompt="question c1"),
            EvalResultWithScores(
                id=2,
                case_id="c2",
                index=2,
                category="sensitive",
                prompt="question c2",
                state="failed",
                error=EvalErrorPayload(code="upstream_error", message="boom"),
            ),
        ],
    )

    assert_compatible(completed, failed)

    response = build_comparison_response(completed, failed)
    error_results = [result for result in response.right.results if result.error is not None]
    assert error_results
    assert error_results[0].error is not None
    assert error_results[0].error.message == "boom"

    markdown = render_comparison_markdown(completed, failed)
    assert "- error: boom" in markdown

    json_payload = json.loads(render_comparison_json(completed, failed))
    right_errors = [result for result in json_payload["right"]["results"] if result.get("error")]
    assert right_errors
    assert right_errors[0]["error"]["message"] == "boom"
