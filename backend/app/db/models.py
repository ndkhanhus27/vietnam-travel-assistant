import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ================================================================
# RAW DOCUMENT
# ================================================================

class RawDocument(Base):
    """
    Dữ liệu nguyên bản từ crawler.

    raw_content giữ nguyên Wikitext.
    Không clean / normalize / transform.
    """

    __tablename__ = "raw_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    source_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    source_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    license: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    raw_content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    content_format: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    revision_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# ================================================================
# PROCESSED DOCUMENT
# ================================================================

class Document(Base):
    """
    Plain-text document sinh ra từ RawDocument.

    Flow:

        RawDocument.raw_content
            ↓
        Wikitext cleaner
            ↓
        plain text
            ↓
        SHA-256
            ↓
        Document
    """

    __tablename__ = "documents"

    __table_args__ = (
        UniqueConstraint(
            "raw_document_id",
            name="uq_documents_raw_document_id",
        ),
        Index(
            "ix_documents_content_hash",
            "content_hash",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Truy ngược được processed document về raw source.
    raw_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "raw_documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Plain text sau cleaning.
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # SHA-256 của plain text.
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    source_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    source_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    license: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    revision_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )