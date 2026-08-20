from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import Settings


def build_engine(settings: Settings | None = None, url: str | None = None) -> Engine:
    database_url = url
    if database_url is None and settings is not None:
        database_url = settings.database_url
    if not database_url:
        database_url = "sqlite:///./data/model-lab.db"
    connect_args: dict[str, object] = {"check_same_thread": False}
    return create_engine(database_url, connect_args=connect_args)
