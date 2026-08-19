from fastapi import FastAPI

from app.api.routes import router
from app.core.config import Settings, load_settings
from app.core.health import Probe, probe_upstream


def create_app(settings: Settings | None = None, probe: Probe | None = None) -> FastAPI:
    app = FastAPI(title="Local AI Model Lab", version="0.1.0")
    app.state.settings = settings or load_settings()
    app.state.probe_upstream = probe if probe is not None else probe_upstream
    app.include_router(router)
    return app


app = create_app()


def run_dev() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")
