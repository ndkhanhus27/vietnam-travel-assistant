from __future__ import annotations

from pipeline.agents.schemas import (
    CoverageResult,
    EvidenceItem,
    EvidenceSource,
    ResearchDepth,
    TaskStatus,
    ToolName,
    ToolObservation,
)
from pipeline.rag.reranker import (
    RerankedChunk,
    TravelReranker,
)

from .utils import normalize_text, sanitize_source_title, source_quality_rank
from .web import WebSearchTool


# ============================================================
# TRAVEL KNOWLEDGE TOOL
# ============================================================

class TravelKnowledgeTool:
    """
    Adaptive travel knowledge retrieval.

    Pipeline:

        query
          ↓
        explicit entities?
          ↓
        retrieve each entity independently
          ↓
        Hybrid RAG
          ↓
        CrossEncoder
          ↓
        entity coverage
          ↓
        missing entity?
          ↓
        Tavily fallback only for missing entity
          ↓
        final coverage
          ↓
        ToolObservation


    Internal RAG hiện tại:

        BGE-M3 Dense
        +
        BM25
        +
        Entity signal
        ↓
        Weighted RRF
        ↓
        CrossEncoder
    """
    @staticmethod
    def _append_unique_evidence(
        *,
        target: list[EvidenceItem],
        incoming: list[EvidenceItem],
        seen_ids: set[str],
    ) -> None:
        """
        Merge evidence mà không duplicate cùng evidence_id.
        """

        for item in incoming:

            if item.evidence_id in seen_ids:
                continue

            seen_ids.add(
                item.evidence_id
            )

            target.append(
                item
            )

    def __init__(
        self,
        web_tool: WebSearchTool | None = None,
    ) -> None:
        """
        Heavy components đều lazy-load.

        Khởi tạo TravelKnowledgeTool không tự:
        - load BGE-M3
        - load CrossEncoder
        - connect Qdrant
        - create Tavily client
        """

        self._retriever: (
            TravelReranker | None
        ) = None

        self._web: (
            WebSearchTool | None
        ) = web_tool

    # ========================================================
    # LAZY RAG
    # ========================================================

    @property
    def retriever(
        self,
    ) -> TravelReranker:

        if self._retriever is None:

            self._retriever = (
                TravelReranker()
            )

        return self._retriever

    # ========================================================
    # LAZY WEB
    # ========================================================

    @property
    def web(
        self,
    ) -> WebSearchTool:

        if self._web is None:

            self._web = (
                WebSearchTool()
            )

        return self._web

    # ========================================================
    # ENTITY MATCHING
    # ========================================================

    @staticmethod
    def _chunk_matches_entity(
        *,
        entity: str,
        chunk: RerankedChunk,
    ) -> bool:
        """
        Kiểm tra chunk RAG có thực sự cover entity.

        Hiện chỉ dùng strong metadata:

        1. document title
        2. primary_entities

        Không dùng toàn bộ `entities`
        vì payload hiện tại có thể chứa
        document-level entities copy vào
        nhiều chunk.
        """

        target = normalize_text(
            entity
        )

        if not target:
            return False

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        title = normalize_text(
            chunk.title
            or ""
        )

        if title:

            if title == target:
                return True

            if target in title:
                return True


        # ----------------------------------------------------
        # PRIMARY ENTITIES
        # ----------------------------------------------------

        for primary in (
            chunk.primary_entities
            or []
        ):

            candidate = normalize_text(
                str(primary)
            )

            if not candidate:
                continue

            if candidate == target:
                return True

            if target in candidate:
                return True


        return False

    # ============================================================
    # RAG CHUNK → UNIFIED EVIDENCE
    # ============================================================
    @staticmethod
    def _to_evidence(
        *,
        chunk: RerankedChunk,
        entity: str | None,
    ) -> EvidenceItem:

        return EvidenceItem(
            evidence_id=(
                f"rag_{chunk.point_id}"
            ),

            source_type=(
                EvidenceSource.RAG
            ),

            title=(
                sanitize_source_title(
                    chunk.title or "",
                    fallback="Travel document",
                )
            ),

            content=(
                chunk.content
            ),

            url=(
                chunk.source_url
                or None
            ),

            entity=entity,

            score=float(
                chunk.rerank_score
            ),

            metadata={
                "point_id": str(
                    chunk.point_id
                ),

                "document_id": str(
                    chunk.document_id
                ),

                "chunk_index": (
                    chunk.chunk_index
                ),

                "rerank_score": float(
                    chunk.rerank_score
                ),

                "hybrid_score": float(
                    chunk.hybrid_score
                ),
                "cross_encoder_score": chunk.cross_encoder_score,

                "source_name": (
                    chunk.source_name
                ),

                "source_quality_rank": source_quality_rank(
                    chunk.source_url
                ),
            },
        )

    # ========================================================
    # ENTITY-SPECIFIC RAG RETRIEVAL
    # ========================================================

    def _retrieve_entity(
        self,
        *,
        query: str,
        entity: str,
        limit: int,
    ) -> tuple[
        list[RerankedChunk],
        list[RerankedChunk],
    ]:
        """
        Retrieve một entity độc lập.

        Ví dụ comparison:

            Bà Nà
                ↓
            retrieval riêng

            Măng Đen
                ↓
            retrieval riêng

        Tránh một entity dominate candidate list.
        """

        retrieval_query = (
            f"{entity}: "
            f"thông tin du lịch cần thiết "
            f"để trả lời câu hỏi "
            f"'{query}'"
        )

        results = (
            self.retriever.search(
                retrieval_query,
                limit=limit,
            )
        )

        matching = [
            chunk
            for chunk in results
            if self._chunk_matches_entity(
                entity=entity,
                chunk=chunk,
            )
        ]

        return (
            results,
            matching,
        )

    # ========================================================
    # WEB FALLBACK
    # ========================================================

    def _fallback_entity_to_web(
        self,
        *,
        query: str,
        entity: str,
    ) -> list[EvidenceItem]:
        """
        Search web ONLY cho entity internal corpus thiếu.

        Example:

            Bà Nà      → RAG ✅
            Măng Đen   → RAG ❌
                            ↓
                         Tavily

        Không search lại Bà Nà.
        """

        research_query = (
            f"{entity} du lịch Việt Nam. "
            f"Cung cấp thông tin liên quan "
            f"để trả lời câu hỏi: {query}"
        )

        return self.web.search(
            query=research_query,
            entity=entity,
            purpose="fallback",
        )
    # ============================================================
    # WEB ENRICHMENT
    # ============================================================


    def _enrich_entity_from_web(
        self,
        *,
        query: str,
        entity: str,
    ) -> list[EvidenceItem]:
        """
        External enrichment cho entity đã được RAG cover.

        Khác fallback:

        fallback:
            corpus thiếu entity

        enrichment:
            corpus đã có entity,
            nhưng cần external evidence để tăng richness.
        """

        research_query = (
            f"{entity} du lịch Việt Nam. "
            f"Tìm thêm thông tin hữu ích, "
            f"đa dạng và liên quan để hỗ trợ "
            f"trả lời câu hỏi: {query}"
        )

        return self.web.search(
            query=research_query,
            entity=entity,
            purpose="enrichment",
        )

    # ========================================================
    # SEARCH
    # ========================================================

    def search(
        self,
        *,
        task_id: str,
        query: str,
        entities: list[str] | None = None,
        require_all_entities: bool = False,
        research_depth: ResearchDepth = ResearchDepth.BASIC,
        limit_per_entity: int = 6,
        max_evidence_per_entity: int = 3,
    ) -> ToolObservation:
        """
        Public API của TravelKnowledgeTool.

        Example:

            search(
                task_id="task_1",
                query=(
                    "Bà Nà và Măng Đen "
                    "khác nhau thế nào?"
                ),
                entities=[
                    "Bà Nà",
                    "Măng Đen",
                ],
                require_all_entities=True,
            )
        """

        query = query.strip()

        # ====================================================
        # INVALID QUERY
        # ====================================================

        if not query:

            return ToolObservation(
                task_id=task_id,

                tool=ToolName.RAG,

                status=TaskStatus.FAILED,

                error=(
                    "Travel knowledge query "
                    "không được rỗng."
                ),
            )

        # ====================================================
        # ENTITY CLEANUP
        # ====================================================

        clean_entities: list[str] = []

        seen_entities: set[str] = set()

        for entity in (
            entities or []
        ):

            entity = str(
                entity
            ).strip()

            if not entity:
                continue

            key = normalize_text(
                entity
            )

            if key in seen_entities:
                continue

            seen_entities.add(
                key
            )

            clean_entities.append(
                entity
            )

        # ====================================================
        # RESULT ACCUMULATORS
        # ====================================================

        evidence: list[
            EvidenceItem
        ] = []

        rag_covered_entities: list[
            str
        ] = []

        rag_missing_entities: list[
            str
        ] = []

        seen_points: set[str] = set()

        seen_evidence_ids: set[str] = set()

        # ====================================================
        # CASE 1 — EXPLICIT ENTITIES
        # ====================================================

        if clean_entities:

            for entity in (
                clean_entities
            ):

                (
                    _all_results,
                    matching_results,
                ) = self._retrieve_entity(
                    query=query,
                    entity=entity,
                    limit=limit_per_entity,
                )

                # -------------------------------------------
                # Corpus chưa cover entity
                # -------------------------------------------

                if not matching_results:

                    rag_missing_entities.append(
                        entity
                    )

                    continue

                rag_covered_entities.append(
                    entity
                )

                # -------------------------------------------
                # Top evidence riêng cho entity
                # -------------------------------------------

                added = 0

                for chunk in (
                    matching_results
                ):

                    point_key = str(
                        chunk.point_id
                    )

                    if (
                        point_key
                        in seen_points
                    ):
                        continue

                    seen_points.add(
                        point_key
                    )

                    rag_evidence = (
                        self._to_evidence(
                            chunk=chunk,
                            entity=entity,
                        )
                    )

                    before = len(evidence)

                    self._append_unique_evidence(
                        target=evidence,
                        incoming=[rag_evidence],
                        seen_ids=seen_evidence_ids,
                    )

                    if len(evidence) == before:
                        continue

                    added += 1

                    if (
                        added
                        >= max_evidence_per_entity
                    ):
                        break

        # ====================================================
        # CASE 2 — NO EXPLICIT ENTITY
        # ====================================================

        else:

            results = (
                self.retriever.search(
                    query,
                    limit=limit_per_entity,
                )
            )

            for chunk in results:

                point_key = str(
                    chunk.point_id
                )

                if (
                    point_key
                    in seen_points
                ):
                    continue

                seen_points.add(
                    point_key
                )

                rag_evidence = (
                    self._to_evidence(
                        chunk=chunk,
                        entity=None,
                    )
                )

                self._append_unique_evidence(
                    target=evidence,
                    incoming=[
                        rag_evidence
                    ],
                    seen_ids=(
                        seen_evidence_ids
                    ),
                )

                if (
                    len(evidence)
                    >= max_evidence_per_entity
                ):
                    break

        # ====================================================
        # WEB FALLBACK FOR MISSING ENTITIES
        # ====================================================

        web_covered_entities: list[
            str
        ] = []

        still_missing_entities: list[
            str
        ] = []

        for entity in (
            rag_missing_entities
        ):

            try:

                web_evidence = (
                    self._fallback_entity_to_web(
                        query=query,
                        entity=entity,
                    )
                )

            except Exception:

                # Provider error không được làm
                # crash cả knowledge tool.
                #
                # Sau này Validator sẽ thấy
                # entity vẫn missing.
                web_evidence = []

            if not web_evidence:

                still_missing_entities.append(
                    entity
                )

                continue

            # -----------------------------------------------
            # Web đã cover entity
            # -----------------------------------------------

            self._append_unique_evidence(
                target=evidence,
                incoming=web_evidence,
                seen_ids=(
                    seen_evidence_ids
                ),
            )

            web_covered_entities.append(
                entity
            )

        # ====================================================
        # FINAL ENTITY COVERAGE
        # ====================================================

        final_covered_entities = (
            rag_covered_entities
            + web_covered_entities
        )

        missing_entities = (
            still_missing_entities
        )

        # ============================================================
        # WEB ENRICHMENT
        # ============================================================

        web_enriched_entities: list[str] = []

        web_enrichment_count = 0

        if (
            research_depth
            == ResearchDepth.ENRICHED
        ):

            # --------------------------------------------------------
            # Có explicit entities:
            #
            # Chỉ enrich entity đã được RAG cover.
            #
            # Entity đã phải fallback web thì không search lại.
            # --------------------------------------------------------

            if clean_entities:

                for entity in rag_covered_entities:

                    try:

                        enrichment = (
                            self._enrich_entity_from_web(
                                query=query,
                                entity=entity,
                            )
                        )

                    except Exception:

                        enrichment = []

                    if not enrichment:
                        continue

                    before = len(
                        evidence
                    )

                    self._append_unique_evidence(
                        target=evidence,
                        incoming=enrichment,
                        seen_ids=(
                            seen_evidence_ids
                        ),
                    )

                    added = (
                        len(evidence)
                        - before
                    )

                    if added > 0:

                        web_enriched_entities.append(
                            entity
                        )

                        web_enrichment_count += (
                            added
                        )

            # --------------------------------------------------------
            # Không có explicit entity:
            #
            # Example:
            # "Gợi ý nơi trekking đẹp ở miền Bắc"
            #
            # RAG + general web enrichment.
            # --------------------------------------------------------

            else:

                try:

                    enrichment = (
                        self.web.search(
                            query=(
                                f"Du lịch Việt Nam. "
                                f"{query}"
                            ),

                            entity=None,

                            purpose="enrichment",
                        )
                    )

                except Exception:

                    enrichment = []

                before = len(
                    evidence
                )

                self._append_unique_evidence(
                    target=evidence,
                    incoming=enrichment,
                    seen_ids=(
                        seen_evidence_ids
                    ),
                )

                web_enrichment_count = (
                    len(evidence)
                    - before
                )

        # ====================================================
        # COVERAGE DECISION
        # ====================================================

        if clean_entities:

            if require_all_entities:

                coverage_sufficient = (
                    len(
                        missing_entities
                    )
                    == 0
                    and bool(
                        final_covered_entities
                    )
                )

            else:

                coverage_sufficient = (
                    bool(
                        final_covered_entities
                    )
                )

        else:

            coverage_sufficient = bool(
                evidence
            )

        coverage = CoverageResult(
            required_entities=(
                clean_entities
            ),

            covered_entities=(
                final_covered_entities
            ),

            missing_entities=(
                missing_entities
            ),

            sufficient=(
                coverage_sufficient
            ),
        )

        # ====================================================
        # FINAL STATUS
        # ====================================================

        success = (
            bool(evidence)
            and coverage_sufficient
        )

        error: str | None = None

        if not evidence:

            error = (
                "Không tìm được evidence "
                "từ RAG hoặc web."
            )

        elif missing_entities:

            error = (
                "Vẫn thiếu evidence cho: "
                + ", ".join(
                    missing_entities
                )
            )

        # ====================================================
        # OBSERVATION
        # ====================================================

        return ToolObservation(
            task_id=task_id,

            tool=ToolName.RAG,

            status=(
                TaskStatus.SUCCESS
                if success
                else TaskStatus.FAILED
            ),

            data={
                "query": query,

                "requested_entities": (
                    clean_entities
                ),

                # -------------------------------------------
                # Diagnostic information
                # -------------------------------------------

                "rag_covered_entities": (
                    rag_covered_entities
                ),

                "rag_missing_entities": (
                    rag_missing_entities
                ),

                "web_covered_entities": (
                    web_covered_entities
                ),

                "covered_entities": (
                    final_covered_entities
                ),

                "missing_entities": (
                    missing_entities
                ),

                "require_all_entities": (
                    require_all_entities
                ),

                "research_depth": (
                    research_depth.value
                ),

                "web_enriched_entities": (
                    web_enriched_entities
                ),

                "web_enrichment_count": (
                    web_enrichment_count
                ),

                "web_fallback_used": (
                    bool(
                        web_covered_entities
                    )
                ),

                "fallback_required": (
                    bool(
                        missing_entities
                    )
                ),
            },

            evidence=evidence,

            coverage=coverage,

            error=error,

            source_count=len(
                evidence
            ),
        )
