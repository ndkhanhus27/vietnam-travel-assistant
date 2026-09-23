import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

from sqlalchemy.dialects.postgresql import ARRAY


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
# ================================================================
# ENTITY
# ================================================================

class Entity(Base):
    """
    Entity canonical sau này được resolve từ AI candidate + Wikidata.

    Ví dụ:
        entity_key = "wikidata:Q..."
    """

    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # ID dùng chung giữa PostgreSQL / Neo4j / Qdrant.
    entity_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    wikidata_qid: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        unique=True,
        index=True,
    )

    name_vi: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
    )

    name_en: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    alt_names: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text),
        nullable=True,
    )

    # city, province, attraction, heritage, beach...
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    # north / central / south
    region: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )

    province: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    parent_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "entities.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    latitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    longitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    unesco_id: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )

    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ================================================================
# DOCUMENT <-> ENTITY
# ================================================================

class DocumentEntity(Base):
    """
    Liên kết nhiều-nhiều giữa Document và Entity.

    role:
        primary
        mention
    """

    __tablename__ = "document_entities"

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "entity_id",
            name="uq_document_entities_document_entity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "entities.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="mention",
        index=True,
    )

    # Text AI nhìn thấy trong document.
    mention_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # title / ai_extraction / wikivoyage_link / manual
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="ai_extraction",
    )

    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
# ================================================================
# ENTITY EXTRACTION RUN
# ================================================================

class EntityExtractionRun(Base):
    """
    Trạng thái extraction theo document + version.
    """

    __tablename__ = (
        "entity_extraction_runs"
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "extractor_version",
            name=(
                "uq_entity_extraction_"
                "document_version"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = (
        mapped_column(
            UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        )
    )

    document_id: Mapped[
        uuid.UUID
    ] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    extractor_version: Mapped[
        str
    ] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    model_name: Mapped[
        str
    ] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[
        str
    ] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
    )

    candidate_count: Mapped[
        int
    ] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    error_message: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[
        datetime
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[
        datetime
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ================================================================
# ENTITY CANDIDATE
# ================================================================

class EntityCandidate(Base):
    """
    AI candidate chưa qua Wikidata resolution.
    """

    __tablename__ = (
        "entity_candidates"
    )

    __table_args__ = (
        UniqueConstraint(
            "extraction_run_id",
            "normalized_name",
            "entity_type",
            name=(
                "uq_candidate_"
                "run_name_type"
            ),
        ),
    )

    id: Mapped[
        uuid.UUID
    ] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    extraction_run_id: Mapped[
        uuid.UUID
    ] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "entity_extraction_runs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    document_id: Mapped[
        uuid.UUID
    ] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    name: Mapped[
        str
    ] = mapped_column(
        Text,
        nullable=False,
    )

    normalized_name: Mapped[
        str
    ] = mapped_column(
        Text,
        nullable=False,
        index=True,
    )

    entity_type: Mapped[
        str
    ] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    role: Mapped[
        str
    ] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )

    mention_text: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    confidence: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    # pending
    # resolved
    # rejected
    resolution_status: Mapped[
        str
    ] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
    )

    resolved_entity_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "entities.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    created_at: Mapped[
        datetime
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )