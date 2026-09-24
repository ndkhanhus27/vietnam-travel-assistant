from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import numpy as np
from qdrant_client import QdrantClient
from rank_bm25 import BM25Okapi

from app.core.config import settings


@dataclass(frozen=True)
class LexicalChunk:
    point_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class Bm25Result:
    point_id: str
    score: float
    rank: int
    payload: dict[str, Any]


def normalize_text(
    text: str,
) -> str:
    text = text or ""

    text = unicodedata.normalize(
        "NFC",
        text,
    )

    return text.casefold().strip()


def tokenize(
    text: str,
) -> list[str]:
    """
    Tokenizer lexical nhẹ cho Vietnamese.

    Dense BGE-M3 sẽ xử lý semantics.
    BM25 chủ yếu hỗ trợ:
        - tên riêng
        - keyword chính xác
        - địa danh
        - cụm từ lexical
    """

    text = normalize_text(text)

    return re.findall(
        r"[0-9a-zA-ZÀ-ỹĐđ]+",
        text,
        flags=re.UNICODE,
    )


class QdrantBm25Index:
    def __init__(self) -> None:

        self.client = QdrantClient(
            url=settings.qdrant_url,
            timeout=60,
        )

        self.collection_name = (
            settings.qdrant_collection
        )

        self.documents: list[
            LexicalChunk
        ] = []

        self.corpus_tokens: list[
            list[str]
        ] = []

        self.bm25: BM25Okapi | None = None

        self._load()

    # ============================================================
    # LOAD ALL CHUNKS FROM QDRANT
    # ============================================================

    def _load(self) -> None:

        offset = None

        while True:

            records, next_offset = (
                self.client.scroll(
                    collection_name=(
                        self.collection_name
                    ),
                    offset=offset,
                    limit=256,
                    with_payload=True,
                    with_vectors=False,
                )
            )

            for record in records:

                payload = (
                    record.payload or {}
                )

                lexical_text = (
                    self._build_lexical_text(
                        payload
                    )
                )

                self.documents.append(
                    LexicalChunk(
                        point_id=str(
                            record.id
                        ),
                        payload=payload,
                    )
                )

                self.corpus_tokens.append(
                    tokenize(
                        lexical_text
                    )
                )

            if next_offset is None:
                break

            offset = next_offset

        if not self.documents:
            raise RuntimeError(
                "Qdrant collection không có "
                "chunk để tạo BM25 index."
            )

        self.bm25 = BM25Okapi(
            self.corpus_tokens
        )

        print(
            "[bm25] loaded "
            f"{len(self.documents)} chunks"
        )

    # ============================================================
    # LEXICAL DOCUMENT
    # ============================================================

    @staticmethod
    def _build_lexical_text(
        payload: dict[str, Any],
    ) -> str:

        title = str(
            payload.get(
                "title",
                "",
            )
        )

        content = str(
            payload.get(
                "content",
                "",
            )
        )

        entities = payload.get(
            "entities",
            [],
        ) or []

        primary_entities = payload.get(
            "primary_entities",
            [],
        ) or []

        # Title + primary entity được repeat nhẹ
        # để proper noun có trọng số lexical tốt hơn.

        parts = [
            title,
            title,
            " ".join(
                str(x)
                for x in primary_entities
            ),
            " ".join(
                str(x)
                for x in primary_entities
            ),
            " ".join(
                str(x)
                for x in entities
            ),
            content,
        ]

        return "\n".join(
            part
            for part in parts
            if part
        )

    # ============================================================
    # SEARCH
    # ============================================================

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[Bm25Result]:

        if self.bm25 is None:
            return []

        query_tokens = tokenize(
            query
        )

        if not query_tokens:
            return []

        scores = self.bm25.get_scores(
            query_tokens
        )

        order = np.argsort(
            scores
        )[::-1]

        results: list[Bm25Result] = []

        for index in order:

            score = float(
                scores[index]
            )

            if score <= 0:
                continue

            document = (
                self.documents[index]
            )

            results.append(
                Bm25Result(
                    point_id=(
                        document.point_id
                    ),
                    score=score,
                    rank=len(results) + 1,
                    payload=document.payload,
                )
            )

            if len(results) >= limit:
                break

        return results

    # ============================================================
    # LOOKUP
    # ============================================================

    def payload_by_id(
        self,
        point_id: str,
    ) -> dict[str, Any] | None:

        for document in self.documents:
            if document.point_id == point_id:
                return document.payload

        return None