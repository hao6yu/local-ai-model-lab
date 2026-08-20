"""Initial SQLite schema for the evaluation portal.

Revision ID: 1_initial
Revises:
Create Date: 2026-08-19 00:00:00.000000
"""

from app.db.models import Base

revision: str = "1_initial"
down_revision: str | None = None


def upgrade(migrate_cmd) -> None:
    Base.metadata.create_all(migrate_cmd.bind)


def downgrade(migrate_cmd) -> None:
    Base.metadata.drop_all(migrate_cmd.bind)
