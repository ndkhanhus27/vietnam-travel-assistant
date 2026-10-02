"""add user admin role

Revision ID: 7f3a2d9c1b04
Revises: c5a9d3187e42
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f3a2d9c1b04"
down_revision: Union[str, Sequence[str], None] = "c5a9d3187e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
