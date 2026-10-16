from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from pipeline.rag.bm25_index import QdrantBm25Index
from pipeline.rag.retriever import DenseRetriever


@dataclass(frozen=True)
class HybridRetrievedChunk:
    point_id: str

    hybrid_score: float

    dense_rank: int | None
    dense_score: float | None

    bm25_rank: int | None
    bm25_score: float | None


    document_id: str
    chunk_index: int

    title: str
    content: str

    source_name: str
    source_url: str


    payload: dict[str, Any]


class HybridRetriever:
    """
    Hybrid retrieval:

        Dense BGE-M3
             +
        BM25 lexical
             ↓
        Weighted RRF
    """

    def __init__(self) -> None:
        # Load the Qdrant-backed lexical index first. If Qdrant is down,
        # fail before allocating the much heavier embedding model.
        self.bm25 = QdrantBm25Index()
        self.dense = DenseRetriever()

    # ============================================================
    # RRF
    # ============================================================

    @staticmethod
    def _rrf(
        *,
        rank: int,
        weight: float,
    ) -> float:
        return weight / (settings.rag_rrf_k + rank)

    # ============================================================
    # SEARCH
    # ============================================================

    def search(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[HybridRetrievedChunk]:
        query = query.strip()

        if not query:
            return []

        if limit is None:
            limit = settings.rag_hybrid_limit

        # --------------------------------------------------------
        # Dense channel
        # --------------------------------------------------------

        dense_results = self.dense.search(
            query,
            limit=settings.rag_dense_candidates,
        )

        # --------------------------------------------------------
        # BM25 channel
        # --------------------------------------------------------

        bm25_results = self.bm25.search(
            query,
            limit=settings.rag_bm25_candidates,
        )

        # --------------------------------------------------------
        # Fusion state
        # --------------------------------------------------------

        fused: dict[str, dict[str, Any]] = {}

        # Dense
        for rank, item in enumerate(
            dense_results,
            start=1,
        ):
            state = fused.setdefault(
                item.point_id,
                {
                    "score": 0.0,
                    "dense_rank": None,
                    "dense_score": None,
                    "bm25_rank": None,
                    "bm25_score": None,
                    "payload": item.payload,
                },
            )

            state["score"] += self._rrf(
                rank=rank,
                weight=settings.rag_rrf_dense_weight,
            )

            state["dense_rank"] = rank
            state["dense_score"] = item.score

        # BM25
        for item in bm25_results:
            state = fused.setdefault(
                item.point_id,
                {
                    "score": 0.0,
                    "dense_rank": None,
                    "dense_score": None,
                    "bm25_rank": None,
                    "bm25_score": None,
                    "payload": item.payload,
                },
            )

            state["score"] += self._rrf(
                rank=item.rank,
                weight=settings.rag_rrf_bm25_weight,
            )

            state["bm25_rank"] = item.rank
            state["bm25_score"] = item.score

        # --------------------------------------------------------
        # Sort by hybrid score
        # --------------------------------------------------------

        ordered = sorted(
            fused.items(),
            key=lambda item: item[1]["score"],
            reverse=True,
        )

        # --------------------------------------------------------
        # Output
        # --------------------------------------------------------

        results: list[HybridRetrievedChunk] = []

        for point_id, state in ordered[:limit]:
            payload = state["payload"] or {}

            results.append(
                HybridRetrievedChunk(
                    point_id=point_id,
                    hybrid_score=float(state["score"]),
                    dense_rank=state["dense_rank"],
                    dense_score=state["dense_score"],
                    bm25_rank=state["bm25_rank"],
                    bm25_score=state["bm25_score"],
                    document_id=str(payload.get("document_id", "")),
                    chunk_index=int(payload.get("chunk_index", 0)),
                    title=str(payload.get("title", "")),
                    content=str(payload.get("content", "")),
                    source_name=str(payload.get("source_name", "")),
                    source_url=str(payload.get("source_url", "")),
                    payload=payload,
                )
            )

        return results
