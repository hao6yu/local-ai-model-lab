import logging
import os

from alembic.context import config as alembic_config
from alembic.context import configure as context_configure
from sqlalchemy import create_engine

from app.db.models import Base

logging.basicConfig(level="INFO")

alembic_config.set_main_option("script_location", os.path.dirname(__file__))

DEFAULT_DATABASE_URL = "sqlite:///./data/model-lab.db"


def get_url() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    return alembic_config.get_main_option("sqlalchemy.url", fallback=DEFAULT_DATABASE_URL)


def run_migrations(migrate_cmd) -> None:
    if migrate_cmd.bind is not None:
        Base.metadata.create_all(migrate_cmd.bind)


def run_migrations_online() -> None:
    engine = create_engine(get_url())
    try:
        with engine.connect() as conn:
            migrate_cmd = context_configure(
                connection=conn.bind,
                target_metadata=Base.metadata,
                render_as_ddl=False,
            )
            run_migrations(migrate_cmd)
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migrations_online()
