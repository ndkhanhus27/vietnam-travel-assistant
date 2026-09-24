from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from sentence_transformers import CrossEncoder

from app.core.config import settings
from pipeline.rag.hybrid_retriever import HybridRetriever, HybridRetrievedChunk


@dataclass(frozen=True)
class RerankedChunk:
    point_id: str

    rerank_rank: int
    rerank_score: float

    hybrid_rank: int
    hybrid_score: float

    dense_rank: int | None
    dense_score: float | None

    bm25_rank: int | None
    bm25_score: float | None

    entity_rank: int | None

    document_id: str
    chunk_index: int

    title: str
    content: str

    source_name: str
    source_url: str

    entities: list[str]
    entity_types: list[str]
    primary_entities: list[str]


class TravelReranker:
    """
    Pipeline:
        query
          ↓
        HybridRetriever
          ↓
        top-N candidates
          ↓
        CrossEncoder
          ↓
        reranked top-K
    """

    def __init__(
        self,
        *,
        retriever: HybridRetriever | None = None,
    ) -> None:
        self.retriever = retriever if retriever is not None else HybridRetriever()

        if torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        print(f"[reranker] model={settings.rag_reranker_model}")
        print(f"[reranker] device={self.device}")

        self.model = CrossEncoder(
            settings.rag_reranker_model,
            device=self.device,
            max_length=settings.rag_reranker_max_length,
        )

    @staticmethod
    def _build_passage(item: HybridRetrievedChunk) -> str:
        """
        Cho reranker thấy cả title + content.
        """
        title = item.title.strip()
        content = item.content.strip()

        if title and content:
            return f"Tiêu đề: {title}\n\n{content}"

        return content or title

    def rerank(
        self,
        *,
        query: str,
        candidates: list[HybridRetrievedChunk],
        limit: int | None = None,
    ) -> list[RerankedChunk]:
        query = query.strip()

        if not query:
            return []

        if not candidates:
            return []

        if limit is None:
            limit = settings.rag_rerank_limit

        pairs = [
            (query, self._build_passage(item))
            for item in candidates
        ]

        scores = self.model.predict(
            pairs,
            batch_size=settings.rag_reranker_batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        scores = np.asarray(scores, dtype=np.float32).reshape(-1)

        if len(scores) != len(candidates):
            raise RuntimeError("Số reranker scores không khớp số candidates.")

        scored = []
        for hybrid_rank, (candidate, rerank_score) in enumerate(zip(candidates, scores), start=1):
            scored.append(
                (
                    float(rerank_score),
                    hybrid_rank,
                    candidate,
                )
            )

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[RerankedChunk] = []

        for rerank_score, hybrid_rank, candidate in scored[:limit]:
            results.append(
                RerankedChunk(
                    point_id=candidate.point_id,

                    rerank_rank=len(results) + 1,
                    rerank_score=rerank_score,

                    hybrid_rank=hybrid_rank,
                    hybrid_score=candidate.hybrid_score,

                    dense_rank=candidate.dense_rank,
                    dense_score=candidate.dense_score,

                    bm25_rank=candidate.bm25_rank,
                    bm25_score=candidate.bm25_score,

                    entity_rank=candidate.entity_rank,

                    document_id=candidate.document_id,
                    chunk_index=candidate.chunk_index,

                    title=candidate.title,
                    content=candidate.content,

                    source_name=candidate.source_name,
                    source_url=candidate.source_url,

                    entities=candidate.entities,
                    entity_types=candidate.entity_types,
                    primary_entities=candidate.primary_entities,
                )
            )

        return results

    def search(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[RerankedChunk]:
        query = query.strip()

        if not query:
            return []

        if limit is None:
            limit = settings.rag_rerank_limit

        hybrid_candidates = self.retriever.search(
            query,
            limit=settings.rag_rerank_candidates,
        )

        return self.rerank(
            query=query,
            candidates=hybrid_candidates,
            limit=limit,
        )