"""add corpus schema

Revision ID: 4c8d2f1a6b90
Revises: 7f3a2d9c1b04
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4c8d2f1a6b90"
down_revision: Union[str, Sequence[str], None] = "7f3a2d9c1b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    # These tables predate Alembic and may already exist in legacy databases.
    # Fresh deployments still need Alembic to establish their schema.
    existing = _table_names()

    if "documents" not in existing:
        op.create_table(
            "documents",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("source_name", sa.String(length=100), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("language", sa.String(length=10), nullable=False),
            sa.Column("license", sa.String(length=100), nullable=True),
            sa.Column("revision_id", sa.String(length=100), nullable=True),
            sa.Column(
                "fetched_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_documents_content_hash"),
            "documents",
            ["content_hash"],
            unique=False,
        )
        op.create_index(
            op.f("ix_documents_language"),
            "documents",
            ["language"],
            unique=False,
        )
    existing = _table_names()
    if "entity_candidates" not in existing:
        op.create_table(
            "entity_candidates",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("document_id", sa.UUID(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("normalized_name", sa.Text(), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("role", sa.String(length=30), nullable=False),
            sa.Column("mention_text", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["document_id"],
                ["documents.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in (
            "document_id",
            "normalized_name",
            "entity_type",
            "role",
        ):
            op.create_index(
                op.f(f"ix_entity_candidates_{column}"),
                "entity_candidates",
                [column],
                unique=False,
            )

def downgrade() -> None:
    existing = _table_names()
    if "entity_candidates" in existing:
        op.drop_table("entity_candidates")
    if "documents" in existing:
        op.drop_table("documents")
