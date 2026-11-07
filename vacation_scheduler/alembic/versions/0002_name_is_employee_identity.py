"""Remove personnel number from employee identity.

Revision ID: 0002_name_is_employee_identity
Revises: 0001_initial_schema
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_name_is_employee_identity"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "employees" not in inspector.get_table_names():
        return
    indexes = {item["name"] for item in inspector.get_indexes("employees")}
    if "uq_employee_org_personnel_number" in indexes:
        op.drop_index("uq_employee_org_personnel_number", table_name="employees")
    columns = {item["name"] for item in inspector.get_columns("employees")}
    if "personnel_number" in columns:
        op.drop_column("employees", "personnel_number")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "employees" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("employees")}
    if "personnel_number" not in columns:
        op.add_column("employees", sa.Column("personnel_number", sa.String(length=50), nullable=True))
    indexes = {item["name"] for item in inspect(bind).get_indexes("employees")}
    if "uq_employee_org_personnel_number" not in indexes:
        op.create_index(
            "uq_employee_org_personnel_number",
            "employees",
            ["organization_id", "personnel_number"],
            unique=True,
            postgresql_where=sa.text("personnel_number IS NOT NULL"),
        )
