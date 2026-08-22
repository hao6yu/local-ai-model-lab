import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from starlette.responses import Response

from app.api import evaluations
from app.api.routes import router
from app.core.config import DATA_DIRECTORY, Settings, load_settings
from app.core.health import Probe, probe_upstream
from app.db.session import init_schema


def _restore_interrupted_runs(engine: Engine) -> None:
    from app.db.models import EvaluationRun
    from app.db.session import session_scope

    with session_scope(engine) as session:
        for run in session.query(EvaluationRun).filter(EvaluationRun.state == "running").all():
            for result in run.results:
                if result.state == "in_progress":
                    result.state = "failed"
            run.state = "failed"
            run.completed_at = datetime.now(UTC)
    session.close()


def create_app(
    settings: Settings | None = None,
    probe: Probe | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    app = FastAPI(title="Local AI Model Lab", version="0.1.0")
    app.state.settings = settings or load_settings()
    app.state.probe_upstream = probe if probe is not None else probe_upstream
    app.state.upstream_transport = upstream_transport
    app.state.generation_lock = asyncio.Lock()
    if app.state.settings.database_url:
        os.makedirs(str(DATA_DIRECTORY), exist_ok=True)
        engine = create_engine(app.state.settings.database_url)
        app.state.engine = engine
        init_schema(engine)
        _restore_interrupted_runs(engine)
    app.include_router(router)
    app.include_router(evaluations.router)
    _mount_frontend(app, app.state.settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    override = settings.static_files_dir
    static_dir = Path(override) if override else (DATA_DIRECTORY.parent / "frontend" / "dist")
    if not static_dir.is_dir():
        return
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

    @app.get("/{full_path:path}", response_model=None)
    async def _spa_fallback(full_path: str) -> Response:
        # Unknown /api/* paths are genuinely missing endpoints, not SPA routes,
        # so return a JSON 404 rather than the HTML shell.
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": f"no such API: /{full_path}"})
        candidate = (static_dir / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html", media_type="text/html; charset=utf-8")


app = create_app()


def run_dev() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")
