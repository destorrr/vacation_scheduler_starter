"""Initial database schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-07
"""
from alembic import op

from app.database import Base
import app.models  # noqa: F401

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Bootstrap migration: create the complete initial SQLAlchemy metadata.
    # Subsequent schema changes must use ordinary, explicit Alembic operations.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
