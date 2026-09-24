from __future__ import annotations

import argparse
import re
import unicodedata
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from pipeline.agent.query_analyzer import (
    QueryAnalysis,
    QueryAnalyzer,
    RetrievalMode,
)

from pipeline.rag.evidence_validator import (
    EvidenceValidator,
)

from pipeline.rag.reranker import (
    RerankedChunk,
    TravelReranker,
)


# ============================================================
# STATE
# ============================================================


class AgentState(TypedDict, total=False):
    # --------------------------------------------------------
    # Input
    # --------------------------------------------------------

    user_query: str

    # --------------------------------------------------------
    # Query Analyzer
    # --------------------------------------------------------

    analysis: QueryAnalysis

    # --------------------------------------------------------
    # Retrieval
    # --------------------------------------------------------

    retrieved_evidence: list[RerankedChunk]

    entity_evidence: dict[
        str,
        list[RerankedChunk],
    ]

    # --------------------------------------------------------
    # Coverage validation
    # --------------------------------------------------------

    covered_entities: list[str]

    missing_entities: list[str]

    evidence_sufficient: bool

    # --------------------------------------------------------
    # Research fallback
    # --------------------------------------------------------

    needs_research: bool

    research_queries: list[str]

    # --------------------------------------------------------
    # Debug/status
    # --------------------------------------------------------

    route_status: str

    errors: list[str]


# ============================================================
# TEXT NORMALIZATION
# ============================================================


def normalize_text(
    value: str,
) -> str:
    """
    Conservative normalization dùng cho entity matching.

    Không semantic match.

    Ví dụ:

        "Bà Nà"
        "bà nà"

    sẽ match nhau.
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
# EVIDENCE COVERAGE GATE
# ============================================================


class EvidenceCoverageGate:
    """
    Kiểm tra RAG evidence có thực sự cover
    các entity mà query yêu cầu hay không.

    QUAN TRỌNG:

    Không dùng document-level `entities` để xác nhận coverage
    vì payload hiện tại copy toàn bộ document entities
    vào mọi chunk.

    Chỉ tin mạnh vào:

    - title
    - primary_entities

    Điều này tránh false positive.
    """

    @staticmethod
    def _matches_normalized_entity(
        target: str,
        candidate: str,
    ) -> bool:

        candidate = normalize_text(
            candidate
        )

        # An empty string is contained in every Python string.
        # Without this guard, missing metadata covers every entity.
        if not candidate:
            return False

        return (
            candidate == target
            or target in candidate
            or candidate in target
        )

    @staticmethod
    def _has_usable_evidence(
        evidence: list[RerankedChunk],
    ) -> bool:

        return (
            EvidenceValidator
            .validate_evidence(evidence)
            .valid
        )

    @staticmethod
    def _entity_matches_chunk(
        entity: str,
        chunk: RerankedChunk,
    ) -> bool:

        target = normalize_text(
            entity
        )

        if not target:
            return False

        # ----------------------------------------------------
        # 1. Title
        # ----------------------------------------------------

        if EvidenceCoverageGate._matches_normalized_entity(
            target,
            chunk.title,
        ):
            return True

        # ----------------------------------------------------
        # 2. Primary entities
        # ----------------------------------------------------

        for primary in (
            chunk.primary_entities
            or []
        ):

            if EvidenceCoverageGate._matches_normalized_entity(
                target,
                primary,
            ):
                return True

        return False

    # ========================================================
    # FILTER ENTITY EVIDENCE
    # ========================================================

    def evidence_for_entity(
        self,
        entity: str,
        evidence: list[
            RerankedChunk
        ],
    ) -> list[RerankedChunk]:

        return [
            item
            for item in evidence
            if self._entity_matches_chunk(
                entity,
                item,
            )
        ]

    # ========================================================
    # COVERAGE CHECK
    # ========================================================

    def validate(
        self,
        *,
        required_entities: list[str],
        evidence: list[
            RerankedChunk
        ],
    ) -> tuple[
        bool,
        list[str],
        list[str],
        dict[
            str,
            list[RerankedChunk],
        ],
    ]:

        # ----------------------------------------------------
        # Query không có explicit entity.
        #
        # Không thể dùng entity coverage gate.
        #
        # Ví dụ:
        # "Tôi thích núi và trời mát, nên đi đâu?"
        # ----------------------------------------------------

        if not required_entities:

            return (
                self._has_usable_evidence(
                    evidence
                ),
                [],
                [],
                {},
            )

        covered: list[str] = []

        missing: list[str] = []

        by_entity: dict[
            str,
            list[RerankedChunk],
        ] = {}

        for entity in required_entities:

            matching = (
                self.evidence_for_entity(
                    entity,
                    evidence,
                )
            )

            matching = [
                item
                for item in matching
                if self._has_usable_evidence(
                    [item]
                )
            ]

            by_entity[
                entity
            ] = matching

            if matching:
                covered.append(
                    entity
                )

            else:
                missing.append(
                    entity
                )

        sufficient = (
            len(missing) == 0
        )

        return (
            sufficient,
            covered,
            missing,
            by_entity,
        )


# ============================================================
# WORKFLOW SERVICE
# ============================================================


class TravelAgentWorkflow:
    """
    STEP 9B.

    Hiện tại workflow làm:

        Query
          ↓
        Analyzer
          ↓
        RAG retrieval
          ↓
        Evidence Coverage Gate
          ↓
        READY
          hoặc
        NEEDS_RESEARCH

    Web research thật sẽ được nối vào ở STEP 9C.
    """

    def __init__(self) -> None:

        self.analyzer = (
            QueryAnalyzer()
        )

        self.retriever = (
            TravelReranker()
        )

        self.coverage_gate = (
            EvidenceCoverageGate()
        )

        self.graph = (
            self._build_graph()
        )

    # ========================================================
    # GRAPH
    # ========================================================

    def _build_graph(self):

        builder = StateGraph(
            AgentState
        )

        builder.add_node(
            "analyze",
            self._analyze_node,
        )

        builder.add_node(
            "retrieve",
            self._retrieve_node,
        )

        builder.add_node(
            "coverage_gate",
            self._coverage_node,
        )

        builder.add_node(
            "research_required",
            self._research_required_node,
        )

        builder.add_node(
            "ready",
            self._ready_node,
        )

        builder.add_edge(
            START,
            "analyze",
        )

        builder.add_conditional_edges(
            "analyze",
            self._route_after_analysis,
            {
                "rag": "retrieve",
                "research": (
                    "research_required"
                ),
                "direct": "ready",
            },
        )

        builder.add_edge(
            "retrieve",
            "coverage_gate",
        )

        builder.add_conditional_edges(
            "coverage_gate",
            self._route_after_coverage,
            {
                "enough": "ready",
                "research": (
                    "research_required"
                ),
            },
        )

        builder.add_edge(
            "research_required",
            END,
        )

        builder.add_edge(
            "ready",
            END,
        )

        return builder.compile()

    # ========================================================
    # ANALYZE NODE
    # ========================================================

    def _analyze_node(
        self,
        state: AgentState,
    ) -> AgentState:

        query = (
            state["user_query"]
            .strip()
        )

        analysis = (
            self.analyzer.analyze(
                query
            )
        )

        return {
            "analysis": analysis,

            "retrieved_evidence": [],

            "entity_evidence": {},

            "covered_entities": [],

            "missing_entities": [],

            "evidence_sufficient": False,

            "needs_research": False,

            "research_queries": [],

            "route_status": (
                "ANALYZED"
            ),

            "errors": [],
        }

    # ========================================================
    # ROUTE AFTER ANALYSIS
    # ========================================================

    @staticmethod
    def _route_after_analysis(
        state: AgentState,
    ) -> str:

        analysis = state[
            "analysis"
        ]

        if (
            analysis.retrieval_mode
            == RetrievalMode.RAG_FIRST
        ):
            return "rag"

        if (
            analysis.retrieval_mode
            == RetrievalMode.WEB_FIRST
        ):
            return "research"

        # WEATHER / ROUTING chưa nối tool thật.
        #
        # Tạm thời đưa sang research/tool-required path
        # thay vì cố nhét vào RAG.

        if (
            analysis.retrieval_mode
            == RetrievalMode.TOOL_ONLY
        ):
            return "research"

        return "direct"

    # ========================================================
    # RETRIEVAL NODE
    # ========================================================

    def _retrieve_node(
        self,
        state: AgentState,
    ) -> AgentState:

        analysis = state[
            "analysis"
        ]

        query = state[
            "user_query"
        ]

        retrieval_queries = (
            analysis.retrieval_queries
            or [query]
        )

        all_results: list[
            RerankedChunk
        ] = []

        seen_points: set[str] = set()

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Search từng retrieval query độc lập.
        #
        # Comparison:
        #
        # Sa Pa     -> retrieval riêng
        # Đà Lạt    -> retrieval riêng
        #
        # rồi mới merge.
        # ----------------------------------------------------

        for retrieval_query in (
            retrieval_queries
        ):

            results = (
                self.retriever.search(
                    retrieval_query,
                    limit=6,
                )
            )

            for item in results:

                if (
                    item.point_id
                    in seen_points
                ):
                    continue

                seen_points.add(
                    item.point_id
                )

                all_results.append(
                    item
                )

        # ----------------------------------------------------
        # Sort lại theo reranker score.
        # ----------------------------------------------------

        all_results.sort(
            key=lambda item: (
                item.rerank_score
            ),
            reverse=True,
        )

        return {
            "retrieved_evidence": (
                all_results
            ),

            "route_status": (
                "RAG_RETRIEVED"
            ),
        }

    # ========================================================
    # COVERAGE NODE
    # ========================================================

    def _coverage_node(
        self,
        state: AgentState,
    ) -> AgentState:

        analysis = state[
            "analysis"
        ]

        evidence = state.get(
            "retrieved_evidence",
            [],
        )

        (
            sufficient,
            covered,
            missing,
            by_entity,
        ) = (
            self.coverage_gate
            .validate(
                required_entities=(
                    analysis
                    .coverage_entities
                ),

                evidence=evidence,
            )
        )

        # ----------------------------------------------------
        # Nếu không có explicit entity:
        #
        # ít nhất phải có retrieval result.
        # ----------------------------------------------------

        if (
            not analysis
            .coverage_entities
            and not evidence
        ):
            sufficient = False

        return {
            "evidence_sufficient": (
                sufficient
            ),

            "covered_entities": (
                covered
            ),

            "missing_entities": (
                missing
            ),

            "entity_evidence": (
                by_entity
            ),

            "needs_research": (
                not sufficient
                and analysis
                .fallback_to_web
            ),

            "route_status": (
                "EVIDENCE_SUFFICIENT"
                if sufficient
                else "EVIDENCE_INSUFFICIENT"
            ),
        }

    # ========================================================
    # ROUTE AFTER COVERAGE
    # ========================================================

    @staticmethod
    def _route_after_coverage(
        state: AgentState,
    ) -> str:

        if state.get(
            "evidence_sufficient",
            False,
        ):
            return "enough"

        return "research"

    # ========================================================
    # RESEARCH REQUIRED NODE
    # ========================================================

    @staticmethod
    def _research_required_node(
        state: AgentState,
    ) -> AgentState:

        analysis = state[
            "analysis"
        ]

        missing = state.get(
            "missing_entities",
            [],
        )

        original_query = state[
            "user_query"
        ]

        research_queries: list[
            str
        ] = []

        # ----------------------------------------------------
        # Best case:
        # chỉ search web cho entity thiếu.
        #
        # Example:
        #
        # Sa Pa ✅
        # Đà Lạt ❌
        #
        # → search Đà Lạt only
        # ----------------------------------------------------

        if missing:

            research_queries = [
                (
                    f"{entity}: "
                    f"{original_query}"
                )
                for entity in missing
            ]

        # ----------------------------------------------------
        # CURRENT_INFO / WEATHER / ROUTING / no evidence.
        # ----------------------------------------------------

        elif (
            analysis.sub_queries
        ):

            research_queries = list(
                analysis.sub_queries
            )

        else:

            research_queries = [
                original_query
            ]

        return {
            "needs_research": True,

            "research_queries": (
                research_queries
            ),

            "route_status": (
                "NEEDS_RESEARCH"
            ),
        }

    # ========================================================
    # READY NODE
    # ========================================================

    @staticmethod
    def _ready_node(
        state: AgentState,
    ) -> AgentState:

        return {
            "needs_research": False,

            "route_status": (
                "READY"
            ),
        }

    # ========================================================
    # PUBLIC API
    # ========================================================

    def run(
        self,
        query: str,
    ) -> AgentState:

        query = query.strip()

        if not query:
            raise ValueError(
                "Query không được rỗng."
            )

        result = self.graph.invoke(
            {
                "user_query": query,
            }
        )

        return result


# ============================================================
# CLI
# ============================================================


def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Vietnam Travel "
            "Agent Workflow"
        )
    )

    parser.add_argument(
        "query",
        nargs="+",
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    query = " ".join(
        args.query
    ).strip()

    workflow = (
        TravelAgentWorkflow()
    )

    result = workflow.run(
        query
    )

    analysis = result[
        "analysis"
    ]

    print()

    print("=" * 90)
    print(
        "STEP 9B - AGENT RAG COVERAGE"
    )
    print("=" * 90)

    print(
        f"Query             : "
        f"{query}"
    )

    print(
        f"Intent            : "
        f"{analysis.intent.value}"
    )

    print(
        f"Retrieval mode    : "
        f"{analysis.retrieval_mode.value}"
    )

    print(
        f"Entities          : "
        f"{analysis.entities}"
    )

    print(
        f"Status            : "
        f"{result.get('route_status')}"
    )

    print(
        f"Evidence count    : "
        f"{len(result.get('retrieved_evidence', []))}"
    )

    print(
        f"Covered entities  : "
        f"{result.get('covered_entities', [])}"
    )

    print(
        f"Missing entities  : "
        f"{result.get('missing_entities', [])}"
    )

    print(
        f"Evidence enough   : "
        f"{result.get('evidence_sufficient', False)}"
    )

    print(
        f"Needs research    : "
        f"{result.get('needs_research', False)}"
    )

    print()

    print("Retrieval queries:")

    for index, value in enumerate(
        analysis.retrieval_queries,
        start=1,
    ):
        print(
            f"  {index}. {value}"
        )

    print()

    print("Research queries:")

    research_queries = (
        result.get(
            "research_queries",
            [],
        )
    )

    if not research_queries:
        print("  -")

    else:

        for index, value in enumerate(
            research_queries,
            start=1,
        ):
            print(
                f"  {index}. {value}"
            )

    print()

    print("Entity evidence:")

    entity_evidence = (
        result.get(
            "entity_evidence",
            {},
        )
    )

    if not entity_evidence:
        print("  -")

    else:

        for entity, items in (
            entity_evidence.items()
        ):

            print(
                f"  {entity}: "
                f"{len(items)} chunks"
            )

            for item in items[:3]:

                print(
                    "      "
                    f"{item.title} "
                    f"(chunk "
                    f"{item.chunk_index}, "
                    f"rerank="
                    f"{item.rerank_score:.3f})"
                )


if __name__ == "__main__":
    main()
