from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qdrant_client import QdrantClient

from app.core.config import settings
from pipeline.rag.embedder import BgeM3Embedder


@dataclass(frozen=True)
class RetrievedChunk:
    point_id: str
    score: float

    document_id: str
    chunk_index: int

    title: str
    content: str

    source_name: str
    source_url: str

    entities: list[str]
    entity_types: list[str]
    primary_entities: list[str]

    payload: dict[str, Any]


class DenseRetriever:
    """
    Dense retrieval:

        user query
            ↓
        BGE-M3 embedding
            ↓
        Qdrant cosine search
            ↓
        top-k chunks
    """

    def __init__(
        self,
        *,
        embedder: BgeM3Embedder | None = None,
    ) -> None:

        self.embedder = (
            embedder
            if embedder is not None
            else BgeM3Embedder()
        )

        self.client = QdrantClient(
            url=settings.qdrant_url,
            timeout=60,
        )

        self.collection_name = (
            settings.qdrant_collection
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[RetrievedChunk]:

        query = query.strip()

        if not query:
            return []

        if limit <= 0:
            raise ValueError(
                "limit phải > 0"
            )

        # --------------------------------------------------------
        # Query -> dense vector
        # --------------------------------------------------------

        query_vector = (
            self.embedder.encode_query(
                query
            )
        )

        # --------------------------------------------------------
        # Vector search
        # --------------------------------------------------------

        response = (
            self.client.query_points(
                collection_name=(
                    self.collection_name
                ),

                query=query_vector,

                limit=limit,

                with_payload=True,
            )
        )

        # --------------------------------------------------------
        # Convert Qdrant points
        # --------------------------------------------------------

        results: list[
            RetrievedChunk
        ] = []

        for point in response.points:

            payload = (
                point.payload
                if point.payload
                else {}
            )

            results.append(
                RetrievedChunk(
                    point_id=str(
                        point.id
                    ),

                    score=float(
                        point.score
                    ),

                    document_id=str(
                        payload.get(
                            "document_id",
                            "",
                        )
                    ),

                    chunk_index=int(
                        payload.get(
                            "chunk_index",
                            0,
                        )
                    ),

                    title=str(
                        payload.get(
                            "title",
                            "",
                        )
                    ),

                    content=str(
                        payload.get(
                            "content",
                            "",
                        )
                    ),

                    source_name=str(
                        payload.get(
                            "source_name",
                            "",
                        )
                    ),

                    source_url=str(
                        payload.get(
                            "source_url",
                            "",
                        )
                    ),

                    entities=list(
                        payload.get(
                            "entities",
                            [],
                        )
                    ),

                    entity_types=list(
                        payload.get(
                            "entity_types",
                            [],
                        )
                    ),

                    primary_entities=list(
                        payload.get(
                            "primary_entities",
                            [],
                        )
                    ),

                    payload=payload,
                )
            )

        return results