from __future__ import annotations

import argparse
import hashlib
import re
import unicodedata

from tavily import TavilyClient

from app.core.config import settings

from pipeline.agents.schemas import (
    CoverageResult,
    EvidenceItem,
    EvidenceSource,
    SubTask,
    TaskStatus,
    ToolName,
    ToolObservation,
)

from pipeline.rag.reranker import (
    RerankedChunk,
    TravelReranker,
)


# ============================================================
# TEXT NORMALIZATION
# ============================================================


def normalize_text(
    value: str,
) -> str:
    """
    Conservative text normalization.

    Dùng cho entity coverage checking.

    Hiện tại:
    - Unicode NFC
    - case-insensitive
    - normalize whitespace

    Không dùng fuzzy matching.
    Không bỏ dấu tiếng Việt.
    """

    value = unicodedata.normalize(
        "NFC",
        value,
    )

    value = value.casefold()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


# ============================================================
# WEB SEARCH TOOL
# ============================================================


class WebSearchTool:
    """
    Tavily web retrieval adapter.

    Nhiệm vụ duy nhất:

        query
          ↓
        Tavily
          ↓
        EvidenceItem[]

    Không:
    - gọi Gemini
    - synthesize answer
    - quyết định final response
    """

    def __init__(self) -> None:

        if not settings.tavily_api_key:
            raise RuntimeError(
                "TAVILY_API_KEY chưa được cấu hình."
            )

        self.client = TavilyClient(
            api_key=settings.tavily_api_key
        )

    # ========================================================
    # EVIDENCE ID
    # ========================================================

    @staticmethod
    def _evidence_id(
        url: str,
    ) -> str:
        """
        Tạo deterministic evidence ID từ URL.

        Không dùng built-in hash()
        vì Python hash có thể khác giữa process.
        """

        digest = hashlib.sha1(
            url.encode(
                "utf-8"
            )
        ).hexdigest()[:16]

        return f"web_{digest}"

    # ========================================================
    # ENTITY COVERAGE
    # ========================================================

    @staticmethod
    def _matches_entity(
        *,
        entity: str,
        title: str,
        content: str,
    ) -> bool:
        """
        Basic deterministic web coverage filter.

        Nếu search dành riêng cho một entity thì
        entity phải thực sự xuất hiện trong
        title hoặc returned content.

        Đây chưa phải semantic web validator.
        """

        target = normalize_text(
            entity
        )

        if not target:
            return True

        combined = normalize_text(
            f"{title} {content}"
        )

        return target in combined

    # ========================================================
    # SEARCH
    # ========================================================

    def search(
        self,
        *,
        query: str,
        entity: str | None = None,
    ) -> list[EvidenceItem]:

        query = query.strip()

        if not query:
            return []

        response = self.client.search(
            query=query,

            search_depth=(
                settings.web_search_depth
            ),

            max_results=(
                settings.web_search_max_results
            ),

            chunks_per_source=(
                settings
                .web_search_chunks_per_source
            ),

            include_answer=False,

            include_raw_content=False,
        )

        results = response.get(
            "results",
            [],
        )

        evidence: list[
            EvidenceItem
        ] = []

        seen_urls: set[str] = set()

        for item in results:

            title = str(
                item.get(
                    "title",
                    "",
                )
            ).strip()

            url = str(
                item.get(
                    "url",
                    "",
                )
            ).strip()

            content = str(
                item.get(
                    "content",
                    "",
                )
            ).strip()

            # ------------------------------------------------
            # Basic validity
            # ------------------------------------------------

            if not url:
                continue

            if not content:
                continue

            # ------------------------------------------------
            # Entity coverage
            # ------------------------------------------------

            if (
                entity
                and not self._matches_entity(
                    entity=entity,
                    title=title,
                    content=content,
                )
            ):
                continue

            # ------------------------------------------------
            # URL deduplication
            # ------------------------------------------------

            if url in seen_urls:
                continue

            seen_urls.add(
                url
            )

            # ------------------------------------------------
            # Tavily score
            # ------------------------------------------------

            raw_score = item.get(
                "score"
            )

            score = (
                float(raw_score)
                if raw_score is not None
                else None
            )

            # ------------------------------------------------
            # Unified evidence
            # ------------------------------------------------

            evidence.append(
                EvidenceItem(
                    evidence_id=(
                        self._evidence_id(
                            url
                        )
                    ),

                    source_type=(
                        EvidenceSource.WEB
                    ),

                    title=(
                        title
                        or url
                    ),

                    content=content,

                    url=url,

                    entity=entity,

                    score=score,

                    metadata={
                        "provider": (
                            "tavily"
                        ),

                        "search_query": (
                            query
                        ),

                        "entity": (
                            entity
                        ),
                    },
                )
            )

        return evidence


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

            if title in target:
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

            if candidate in target:
                return True

        return False
    
    # ============================================================
    # TOOL REGISTRY
    # ============================================================


    class ToolRegistry:
        """
        Single execution boundary cho Agent System.

        Planner chỉ tạo SubTask.

        LangGraph sau này chỉ gọi:

            registry.execute(task)

        Registry chịu trách nhiệm dispatch tới đúng tool.

        Hiện implement thật:
            - search_travel_knowledge
            - web_search

        Các tool khác sẽ được fill dần:
            - weather
            - map_location
            - routing
            - budget_calculator
        """

        def __init__(
            self,
            web_tool: WebSearchTool | None = None,
        ) -> None:
            """
            Dependencies vẫn lazy.

            web_tool có thể được inject từ ToolRegistry
            để direct web search và RAG fallback
            dùng chung một Tavily client.
            """

            self._web: (
                WebSearchTool | None
            ) = web_tool

            self._knowledge: (
                TravelKnowledgeTool | None
            ) = None

        # ========================================================
        # LAZY DEPENDENCIES
        # ========================================================

        @property
        def web(
            self,
        ) -> WebSearchTool:

            if self._web is None:

                if self._knowledge is not None:
                    self._web = (
                        self._knowledge.web
                    )
                else:
                    self._web = (
                        WebSearchTool()
                    )

            return self._web

        @property
        def knowledge(
            self,
        ) -> TravelKnowledgeTool:

            if self._knowledge is None:

                self._knowledge = (
                    TravelKnowledgeTool(
                        web_tool=self._web
                    )
                )

            return self._knowledge

        # ========================================================
        # FAILED OBSERVATION
        # ========================================================

        @staticmethod
        def _failed(
            *,
            task: SubTask,
            message: str,
        ) -> ToolObservation:

            return ToolObservation(
                task_id=task.task_id,

                tool=task.tool,

                status=TaskStatus.FAILED,

                error=message,

                source_count=0,
            )

        # ========================================================
        # TRAVEL KNOWLEDGE
        # ========================================================

        def _execute_rag(
            self,
            task: SubTask,
        ) -> ToolObservation:

            arguments = (
                task.arguments
            )

            query = str(
                arguments.get(
                    "query",
                    "",
                )
            ).strip()

            raw_entities = arguments.get(
                "entities",
                [],
            )

            if not isinstance(
                raw_entities,
                list,
            ):

                return self._failed(
                    task=task,
                    message=(
                        "'entities' phải là list."
                    ),
                )

            entities = [
                str(entity).strip()
                for entity in raw_entities
                if str(entity).strip()
            ]

            require_all_entities = bool(
                arguments.get(
                    "require_all_entities",
                    False,
                )
            )

            if not query:

                return self._failed(
                    task=task,
                    message=(
                        "search_travel_knowledge "
                        "thiếu argument 'query'."
                    ),
                )

            return self.knowledge.search(
                task_id=task.task_id,

                query=query,

                entities=entities,

                require_all_entities=(
                    require_all_entities
                ),
            )

        # ========================================================
        # WEB SEARCH
        # ========================================================

        def _execute_web(
            self,
            task: SubTask,
        ) -> ToolObservation:

            arguments = (
                task.arguments
            )

            query = str(
                arguments.get(
                    "query",
                    "",
                )
            ).strip()

            entity_raw = arguments.get(
                "entity"
            )

            entity = (
                str(entity_raw).strip()
                if entity_raw is not None
                else None
            )

            if entity == "":
                entity = None

            if not query:

                return self._failed(
                    task=task,
                    message=(
                        "web_search thiếu "
                        "argument 'query'."
                    ),
                )

            try:

                evidence = (
                    self.web.search(
                        query=query,
                        entity=entity,
                    )
                )

            except Exception as exc:

                return self._failed(
                    task=task,
                    message=(
                        f"Web search failed: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )

            if not evidence:

                return self._failed(
                    task=task,
                    message=(
                        "Web search không tìm "
                        "được evidence phù hợp."
                    ),
                )

            return ToolObservation(
                task_id=task.task_id,

                tool=task.tool,

                status=TaskStatus.SUCCESS,

                data={
                    "query": query,
                    "entity": entity,
                    "provider": "tavily",
                },

                evidence=evidence,

                coverage=None,

                error=None,

                source_count=len(
                    evidence
                ),
            )

        # ========================================================
        # PUBLIC EXECUTE
        # ========================================================

        def execute(
            self,
            task: SubTask,
        ) -> ToolObservation:
            """
            Dispatch một SubTask tới implementation thật.
            """

            try:

                if task.tool == ToolName.RAG:

                    return self._execute_rag(
                        task
                    )

                if (
                    task.tool
                    == ToolName.WEB_SEARCH
                ):

                    return self._execute_web(
                        task
                    )

                # -----------------------------------------------
                # Chưa implement.
                #
                # Không fake result.
                # Không silently fallback sang Gemini/web.
                # -----------------------------------------------

                return self._failed(
                    task=task,
                    message=(
                        "Tool chưa được implement: "
                        f"{task.tool.value}"
                    ),
                )

            except Exception as exc:

                return self._failed(
                    task=task,
                    message=(
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )
    
    # ========================================================
    # RAG CHUNK → UNIFIED EVIDENCE
    # ========================================================

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
                chunk.title
                or "Travel document"
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

                "source_name": (
                    chunk.source_name
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

                    evidence.append(
                        self._to_evidence(
                            chunk=chunk,
                            entity=entity,
                        )
                    )

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

                evidence.append(
                    self._to_evidence(
                        chunk=chunk,
                        entity=None,
                    )
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

            evidence.extend(
                web_evidence
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


# ToolRegistry is implemented alongside TravelKnowledgeTool above.
# Export it at module level so callers can import the public API directly.
ToolRegistry = TravelKnowledgeTool.ToolRegistry


# ============================================================
# CLI
# ============================================================


def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Travel Knowledge Tool Test"
        )
    )

    parser.add_argument(
        "query",
        nargs="+",
    )

    parser.add_argument(
        "--entities",
        nargs="*",
        default=[],
    )

    parser.add_argument(
        "--require-all",
        action="store_true",
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    query = " ".join(
        args.query
    ).strip()

    tool = (
        TravelKnowledgeTool()
    )

    result = tool.search(
        task_id="manual_test",

        query=query,

        entities=(
            args.entities
        ),

        require_all_entities=(
            args.require_all
        ),
    )

    print()

    print("=" * 90)
    print(
        "STEP 3B - ADAPTIVE TRAVEL KNOWLEDGE TOOL"
    )
    print("=" * 90)

    print(
        f"Query             : "
        f"{query}"
    )

    print(
        f"Status            : "
        f"{result.status.value}"
    )

    print(
        f"Source count      : "
        f"{result.source_count}"
    )

    print(
        f"Error             : "
        f"{result.error}"
    )

    # ========================================================
    # COVERAGE
    # ========================================================

    print()

    if result.coverage:

        print(
            f"Required entities : "
            f"{result.coverage.required_entities}"
        )

        print(
            f"Covered entities  : "
            f"{result.coverage.covered_entities}"
        )

        print(
            f"Missing entities  : "
            f"{result.coverage.missing_entities}"
        )

        print(
            f"Coverage enough   : "
            f"{result.coverage.sufficient}"
        )

    # ========================================================
    # DIAGNOSTICS
    # ========================================================

    rag_covered_entities = result.data.get(
        "rag_covered_entities",
        [],
    )
    rag_missing_entities = result.data.get(
        "rag_missing_entities",
        [],
    )
    web_covered_entities = result.data.get(
        "web_covered_entities",
        [],
    )
    web_fallback_used = result.data.get(
        "web_fallback_used",
        False,
    )
    fallback_required = result.data.get(
        "fallback_required",
        False,
    )

    print()

    print(
        f"RAG covered       : "
        f"{rag_covered_entities}"
    )

    print(
        f"RAG missing       : "
        f"{rag_missing_entities}"
    )

    print(
        f"Web covered       : "
        f"{web_covered_entities}"
    )

    print(
        f"Web fallback used : "
        f"{web_fallback_used}"
    )

    print(
        f"Fallback required : "
        f"{fallback_required}"
    )

    # ========================================================
    # EVIDENCE
    # ========================================================

    print()
    print("EVIDENCE")

    if not result.evidence:

        print("  -")

    for index, item in enumerate(
        result.evidence,
        start=1,
    ):

        print()

        print(
            f"[{index}] "
            f"{item.title}"
        )

        print(
            f"    entity : "
            f"{item.entity}"
        )

        print(
            f"    score  : "
            f"{item.score}"
        )

        print(
            f"    type   : "
            f"{item.source_type.value}"
        )

        print(
            f"    url    : "
            f"{item.url}"
        )

        preview = (
            item.content[:180]
            .replace(
                "\n",
                " ",
            )
        )

        print(
            f"    text   : "
            f"{preview}..."
        )


if __name__ == "__main__":
    main()
