from __future__ import annotations

import uuid

from pydantic import BaseModel


class RagChunk(BaseModel):
    chunk_id: str

    document_id: uuid.UUID
    chunk_index: int

    title: str
    content: str

    token_count: int

    source_name: str
    source_url: str
    language: str

    fetched_at: str | None = None

    entities: list[str]
    entity_types: list[str]