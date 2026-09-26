from __future__ import annotations

import asyncio
from typing import Any, cast

from langgraph.graph import (
    END,
    START,
    StateGraph,
)

from pipeline.agents.executor import (
    ToolExecutor,
)

from pipeline.agents.planner import (
    TravelPlanner,
)

from pipeline.agents.state import (
    AgentState,
)

from pipeline.agents.tools import (
    ResearchEvidenceAggregator,
)

from pipeline.agents.validator import (
    AgentValidator,
)


MAX_RETRIES = 1


# ============================================================
# RESEARCH WORKFLOW
# ============================================================


class TravelAgentWorkflow:
    """
    LangGraph orchestration layer.

    Current graph:

        START
          ↓
        planner
          ↓
        executor
          ↓
        research_aggregator
          ↓
        validator
          ├── valid ────────────────→ END
          ├── recoverable ─→ retry ─→ executor
          └── non-recoverable ──────→ END

    Chưa gồm:

        - selective task retry
        - reasoner
        - synthesizer
        - conversation memory

    Mục tiêu hiện tại là chứng minh LangGraph có thể
    orchestration các component đã test độc lập.
    """

    def __init__(
        self,
        *,
        planner: TravelPlanner | None = None,
        executor: ToolExecutor | None = None,
        aggregator: (
            ResearchEvidenceAggregator | None
        ) = None,
        validator: AgentValidator | None = None,
    ) -> None:

        self.planner = (
            planner
            if planner is not None
            else TravelPlanner()
        )

        self.executor = (
            executor
            if executor is not None
            else ToolExecutor()
        )

        self.aggregator = (
            aggregator
            if aggregator is not None
            else ResearchEvidenceAggregator()
        )

        self.validator = (
            validator
            if validator is not None
            else AgentValidator()
        )

        self.graph = (
            self._build_graph()
        )

    # ========================================================
    # NODE 1
    # PLANNER
    # ========================================================

    async def planner_node(
        self,
        state: AgentState,
    ) -> dict[str, Any]:
        """
        User query
            ↓
        TravelPlanner
            ↓
        ExecutionPlan

        TravelPlanner hiện synchronous và gọi external LLM,
        nên dùng asyncio.to_thread() để không block event loop.
        """

        query = (
            state.get(
                "query",
                "",
            )
            .strip()
        )

        if not query:

            raise ValueError(
                "AgentState.query is required."
            )

        plan = await asyncio.to_thread(
            self.planner.plan,
            query,
        )

        return {
            "plan": plan,
        }

    # ========================================================
    # NODE 2
    # TOOL EXECUTOR
    # ========================================================

    async def executor_node(
        self,
        state: AgentState,
    ) -> dict[str, Any]:
        """
        ExecutionPlan
            ↓
        ToolExecutor
            ↓
        list[ToolObservation]

        ToolExecutor tự xử lý:
            - dependency DAG
            - parallel execution
            - failed dependency -> skipped
            - stable output order
        """

        plan = state.get(
            "plan"
        )

        if plan is None:

            raise ValueError(
                "executor_node requires "
                "state.plan."
            )

        observations = (
            await self.executor.execute(
                plan
            )
        )

        return {
            "observations": observations,
        }

    # ========================================================
    # NODE 3
    # RESEARCH EVIDENCE AGGREGATOR
    # ========================================================

    async def research_aggregator_node(
        self,
        state: AgentState,
    ) -> dict[str, Any]:
        """
        Tool observations
            ↓
        ResearchEvidenceAggregator
            ↓
        RAG + WEB research evidence

        Weather / Routing / Budget không đi vào đây.
        Chúng vẫn còn nguyên trong state.observations.
        """

        observations = (
            state.get(
                "observations",
                [],
            )
        )

        research_evidence = (
            self.aggregator.aggregate(
                observations
            )
        )

        return {
            "research_evidence": (
                research_evidence
            ),
        }

    # ========================================================
    # NODE 4
    # DETERMINISTIC VALIDATOR
    # ========================================================

    async def validator_node(
        self,
        state: AgentState,
    ) -> dict[str, Any]:

        plan = state.get(
            "plan"
        )

        if plan is None:

            raise ValueError(
                "validator_node requires "
                "state.plan."
            )

        observations = (
            state.get(
                "observations",
                [],
            )
        )

        research_evidence = (
            state.get(
                "research_evidence",
                [],
            )
        )

        validation = (
            self.validator.validate(
                plan=plan,
                observations=observations,
                research_evidence=(
                    research_evidence
                ),
            )
        )

        return {
            "validation": validation,
        }

    # ========================================================
    # NODE 5
    # BOUNDED RETRY COUNTER
    # ========================================================

    async def retry_node(
        self,
        state: AgentState,
    ) -> dict[str, Any]:
        """
        Tăng retry counter.

        Node này không execute tool trực tiếp. Sau node này,
        graph quay lại executor và chạy lại toàn ExecutionPlan.
        """

        retry_count = state.get(
            "retry_count",
            0,
        )

        return {
            "retry_count": retry_count + 1,
        }

    # ========================================================
    # CONDITIONAL ROUTER
    # ========================================================

    def route_after_validation(
        self,
        state: AgentState,
    ) -> str:
        """
        Quyết định flow sau validation.

        Returns:
            "done"
            "retry"
            "degraded"
        """

        validation = state.get(
            "validation"
        )

        if validation is None:

            raise ValueError(
                "route_after_validation "
                "requires state.validation."
            )

        if validation.valid:
            return "done"

        # Invalid nhưng không có issue là state không nhất quán.
        # Retry không thể sửa một failure không có nguyên nhân.
        if not validation.issues:
            return "degraded"

        if any(
            not issue.recoverable
            for issue in validation.issues
        ):
            return "degraded"

        retry_count = state.get(
            "retry_count",
            0,
        )

        if retry_count < MAX_RETRIES:
            return "retry"

        return "degraded"

    # ========================================================
    # GRAPH
    # ========================================================

    def _build_graph(self):

        builder = StateGraph(
            AgentState
        )

        # ----------------------------------------------------
        # NODES
        # ----------------------------------------------------

        builder.add_node(
            "planner",
            self.planner_node,
        )

        builder.add_node(
            "executor",
            self.executor_node,
        )

        builder.add_node(
            "research_aggregator",
            self.research_aggregator_node,
        )

        builder.add_node(
            "validator",
            self.validator_node,
        )

        builder.add_node(
            "retry",
            self.retry_node,
        )

        # ----------------------------------------------------
        # EDGES
        # ----------------------------------------------------

        builder.add_edge(
            START,
            "planner",
        )

        builder.add_edge(
            "planner",
            "executor",
        )

        builder.add_edge(
            "executor",
            "research_aggregator",
        )

        builder.add_edge(
            "research_aggregator",
            "validator",
        )

        builder.add_conditional_edges(
            "validator",
            self.route_after_validation,
            {
                "done": END,
                "retry": "retry",
                "degraded": END,
            },
        )

        builder.add_edge(
            "retry",
            "executor",
        )

        return builder.compile()

    # ========================================================
    # PUBLIC ASYNC API
    # ========================================================

    async def run(
        self,
        query: str,
    ) -> AgentState:
        """
        Production-style async execution.
        """

        initial_state: AgentState = {
            "query": query,
            "retry_count": 0,
        }

        result = await self.graph.ainvoke(
            initial_state
        )

        return cast(
            AgentState,
            result,
        )

    # ========================================================
    # SYNC CONVENIENCE API
    # ========================================================

    def run_sync(
        self,
        query: str,
    ) -> AgentState:
        """
        Convenience cho CLI/test.

        FastAPI async endpoint sau này nên dùng:

            await workflow.run(query)
        """

        return asyncio.run(
            self.run(
                query
            )
        )


# ============================================================
# MODULE-LEVEL FACTORY
# ============================================================


def build_workflow() -> TravelAgentWorkflow:

    return TravelAgentWorkflow()
