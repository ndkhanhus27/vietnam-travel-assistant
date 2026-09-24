from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from app.core.config import settings


class TravelQdrantStore:
    def __init__(self) -> None:
        self.client = QdrantClient(
            url=settings.qdrant_url,
            timeout=60,
        )
        self.collection_name = settings.qdrant_collection

    def recreate_collection(
        self,
    ) -> None:
        """
        Xóa collection cũ và tạo lại.

        Chỉ dùng khi rebuild full index.
        """

        if self.client.collection_exists(self.collection_name):
            print("[qdrant] deleting old collection...")

            self.client.delete_collection(
                collection_name=self.collection_name
            )

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=settings.rag_vector_size,
                distance=Distance.COSINE,
            ),
        )

        print(f"[qdrant] collection created: {self.collection_name}")

    def ensure_collection(
        self,
    ) -> None:
        if self.client.collection_exists(self.collection_name):
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=settings.rag_vector_size,
                distance=Distance.COSINE,
            ),
        )

    def upsert(
        self,
        points: list[PointStruct],
    ) -> None:
        if not points:
            return

        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=True,
        )

    def count(
        self,
    ) -> int:
        result = self.client.count(
            collection_name=self.collection_name,
            exact=True,
        )

        return int(result.count)
