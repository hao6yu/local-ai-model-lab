import os

from sqlalchemy import create_engine

from alembic import context
from app.db.models import Base

DEFAULT_DATABASE_URL = "sqlite:///./data/model-lab.db"


def get_url() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    return context.config.get_main_option("sqlalchemy.url", DEFAULT_DATABASE_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        render_as_ddl=True,
        as_sqlite=get_url().startswith("sqlite"),
        target_metadata=Base.metadata,
        version_table="alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url())
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            autogenerate=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
