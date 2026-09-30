from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

from langgraph.config import get_stream_writer
from langgraph.graph import (
    END,
    START,
    StateGraph,
)

from pipeline.agents.context import (
    ContextBuilder,
    ConversationContext,
    ConversationRole,
)

from pipeline.agents.executor import (
    ToolExecutor,
)

from pipeline.agents.llm_runtime import (
    GeminiRuntime,
)

from pipeline.agents.planner import (
    TravelPlanner,
)

from pipeline.agents.reasoner import (
    TravelReasoner,
)

from pipeline.agents.schemas import (
    AgentResponse,
    AgentResponseType,
    ClarificationRequest,
)

from pipeline.agents.state import (
    AgentState,
)

from pipeline.agents.synthesizer import (
    TravelSynthesizer,
)

from pipeline.agents.tools import (
    ResearchEvidenceAggregator,
)

from pipeline.agents.validator import (
    AgentValidator,
)


MAX_RETRIES = 1

PUBLIC_STAGE_MESSAGES = {
    "planning": "Đang phân tích yêu cầu",
    "retrieving": "Đang tìm thông tin du lịch",
    "validating": "Đang kiểm tra thông tin",
    "reasoning": "Đang sắp xếp thông tin",
    "generating": "Đang chuẩn bị câu trả lời",
}


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
          ├── clarification ─→ clarification_response ─→ END
          └── execute
                ↓
              executor
          ↓
        research_aggregator
          ↓
        validator
          ├── valid ────────────────→ reasoner
          ├── recoverable ─→ retry ─→ executor
          └── non-recoverable ──────→ reasoner
                                        ↓
                                    synthesizer
                                        ↓
                                       END

    Chưa gồm:

        - selective task retry
        - persisted conversation memory

    Mục tiêu hiện tại là chứng minh LangGraph có thể
    orchestration các component đã test độc lập.
    """

    def __init__(
        self,
        *,
        context_builder: ContextBuilder | None = None,
        planner: TravelPlanner | None = None,
        executor: ToolExecutor | None = None,
        aggregator: (
            ResearchEvidenceAggregator | None
        ) = None,
        validator: AgentValidator | None = None,
        reasoner: TravelReasoner | None = None,
        synthesizer: TravelSynthesizer | None = None,
        llm_runtime: GeminiRuntime | None = None,
    ) -> None:

        runtime = llm_runtime

        if (
            runtime is None
            and (
                planner is None
                or reasoner is None
                or synthesizer is None
            )
        ):
            runtime = GeminiRuntime()

        self.llm_runtime = runtime

        self.context_builder = (
            context_builder
            if context_builder is not None
            else ContextBuilder()
        )

        self.planner = (
            planner
            if planner is not None
            else TravelPlanner(
                context_builder=(
                    self.context_builder
                ),
                llm_runtime=runtime,
            )
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

        self.reasoner = (
            reasoner
            if reasoner is not None
            else TravelReasoner(
                llm_runtime=runtime
            )
        )

        self.synthesizer = (
            synthesizer
            if synthesizer is not None
            else TravelSynthesizer(
                llm_runtime=runtime
            )
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

        previous_context = state.get(
            "conversation_context"
        )

        plan = await asyncio.to_thread(
            self.planner.plan,
            query,
            context=previous_context,
        )

        context = (
            self.context_builder
            .update_after_plan(
                previous_context=(
                    previous_context
                ),
                query=query,
                plan=plan,
            )
        )

        return {
            "plan": plan,
            "conversation_context": context,
        }

    # ========================================================
    # NODE 2
    # CLARIFICATION RESPONSE
    # ========================================================

    @staticmethod
    def _clarification_text(
        request: ClarificationRequest,
    ) -> str:

        parts: list[str] = []

        if request.question:
            parts.append(
                request.question
            )

        for field in request.fields:

            if field.question in parts:
                continue

            parts.append(
                field.question
            )

        return "\n".join(
            parts
        )

    async def clarification_node(
        self,
        state: AgentState,
    ) -> dict[str, Any]:
        """
        Convert Planner clarification output into the public response.

        This node is deterministic and intentionally does not execute
        tools, reasoning, or synthesis.
        """

        plan = state.get(
            "plan"
        )

        if plan is None:

            raise ValueError(
                "clarification_node requires "
                "state.plan."
            )

        request = plan.clarification

        if request is None:

            raise ValueError(
                "clarification_node requires "
                "plan.clarification."
            )

        response = AgentResponse(
            response_type=(
                AgentResponseType
                .CLARIFICATION
            ),
            answer="",
            clarification=request,
            citations=[],
            intent=plan.intent,
            used_tools=[],
            suggested_followups=[],
            degraded=False,
        )

        context = state.get(
            "conversation_context"
        )

        clarification_text = (
            self._clarification_text(
                request
            )
        )

        if (
            context is not None
            and clarification_text
        ):

            context = (
                self.context_builder
                .append_message(
                    context,
                    role=(
                        ConversationRole
                        .ASSISTANT
                    ),
                    content=(
                        clarification_text
                    ),
                )
            )

        return {
            "response": response,
            "conversation_context": context,
        }

    # ========================================================
    # NODE 3
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
                plan,
                event_sink=get_stream_writer(),
            )
        )

        return {
            "observations": observations,
        }

    # ========================================================
    # NODE 4
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
    # NODE 5
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
    # NODE 6
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
    # NODE 7
    # STRUCTURED ANSWER REASONER
    # ========================================================

    async def reasoner_node(
        self,
        state: AgentState,
    ) -> dict[str, Any]:

        query = (
            state.get(
                "query",
                "",
            )
            .strip()
        )

        plan = state.get(
            "plan"
        )

        validation = state.get(
            "validation"
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

        if not query:

            raise ValueError(
                "reasoner_node requires "
                "state.query."
            )

        if plan is None:

            raise ValueError(
                "reasoner_node requires "
                "state.plan."
            )

        if validation is None:

            raise ValueError(
                "reasoner_node requires "
                "state.validation."
            )

        reasoner_output = (
            await asyncio.to_thread(
                self.reasoner.reason,
                query=query,
                plan=plan,
                observations=observations,
                research_evidence=(
                    research_evidence
                ),
                validation=validation,
            )
        )

        return {
            "reasoner_output": (
                reasoner_output
            ),
        }

    # ========================================================
    # NODE 8
    # FINAL RESPONSE SYNTHESIZER
    # ========================================================

    async def synthesizer_node(
        self,
        state: AgentState,
    ) -> dict[str, Any]:

        query = (
            state.get(
                "query",
                "",
            )
            .strip()
        )

        plan = state.get(
            "plan"
        )

        reasoner_output = state.get(
            "reasoner_output"
        )

        validation = state.get(
            "validation"
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

        if not query:

            raise ValueError(
                "synthesizer_node requires "
                "state.query."
            )

        if plan is None:

            raise ValueError(
                "synthesizer_node requires "
                "state.plan."
            )

        if reasoner_output is None:

            raise ValueError(
                "synthesizer_node requires "
                "state.reasoner_output."
            )

        if validation is None:

            raise ValueError(
                "synthesizer_node requires "
                "state.validation."
            )

        response = await asyncio.to_thread(
            self.synthesizer.synthesize,
            query=query,
            plan=plan,
            reasoner_output=reasoner_output,
            observations=observations,
            research_evidence=(
                research_evidence
            ),
            validation=validation,
        )

        context = state.get(
            "conversation_context"
        )

        if (
            context is not None
            and response.answer.strip()
        ):

            context = (
                self.context_builder
                .append_message(
                    context,
                    role=(
                        ConversationRole
                        .ASSISTANT
                    ),
                    content=response.answer,
                )
            )

        return {
            "response": response,
            "conversation_context": context,
        }

    # ========================================================
    # CONDITIONAL ROUTER
    # ========================================================

    @staticmethod
    def route_after_planner(
        state: AgentState,
    ) -> str:
        """
        Route only from the Planner's explicit clarification contract.

        An empty subtask list is not sufficient: direct-answer intents
        may legitimately have no tools.
        """

        plan = state.get(
            "plan"
        )

        if plan is None:

            raise ValueError(
                "route_after_planner requires "
                "state.plan."
            )

        if plan.clarification is not None:
            return "clarification"

        return "execute"

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
            "clarification",
            self.clarification_node,
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

        builder.add_node(
            "reasoner",
            self.reasoner_node,
        )

        builder.add_node(
            "synthesizer",
            self.synthesizer_node,
        )

        # ----------------------------------------------------
        # EDGES
        # ----------------------------------------------------

        builder.add_edge(
            START,
            "planner",
        )

        builder.add_conditional_edges(
            "planner",
            self.route_after_planner,
            {
                "clarification": (
                    "clarification"
                ),
                "execute": "executor",
            },
        )

        builder.add_edge(
            "clarification",
            END,
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
                "done": "reasoner",
                "retry": "retry",
                "degraded": "reasoner",
            },
        )

        builder.add_edge(
            "retry",
            "executor",
        )

        builder.add_edge(
            "reasoner",
            "synthesizer",
        )

        builder.add_edge(
            "synthesizer",
            END,
        )

        return builder.compile()

    # ========================================================
    # PUBLIC ASYNC API
    # ========================================================

    async def run(
        self,
        query: str,
        *,
        context: (
            ConversationContext | None
        ) = None,
    ) -> AgentState:
        """
        Production-style async execution.
        """

        initial_state = self._initial_state(query, context)

        result = await self.graph.ainvoke(
            initial_state
        )

        return cast(
            AgentState,
            result,
        )

    async def stream(
        self,
        query: str,
        *,
        context: ConversationContext | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any] | AgentState]]:
        state = self._initial_state(query, context)

        yield (
            "progress",
            _stage_event("planning"),
        )

        async for mode, chunk in self.graph.astream(
            state,
            stream_mode=["updates", "custom"],
        ):
            if mode == "custom":
                if isinstance(chunk, dict) and chunk.get("type") == "tool":
                    yield "progress", chunk
                continue

            if mode != "updates" or not isinstance(chunk, dict):
                continue

            for node_name, update in chunk.items():
                if isinstance(update, dict):
                    state.update(update)
                stage = self._public_stage_after_node(node_name, state)
                if stage is not None:
                    yield "progress", _stage_event(stage)

        yield "result", cast(AgentState, state)

    @staticmethod
    def _initial_state(
        query: str,
        context: ConversationContext | None,
    ) -> AgentState:
        return {
            "query": query,
            "retry_count": 0,
            "conversation_context": (
                context
                if context is not None
                else ConversationContext()
            ),
        }

    def _public_stage_after_node(
        self,
        node_name: str,
        state: AgentState,
    ) -> str | None:
        if node_name == "planner":
            plan = state.get("plan")
            if plan is not None and plan.clarification is not None:
                return "generating"
            return "retrieving"
        if node_name == "research_aggregator":
            return "validating"
        if node_name == "validator":
            return (
                "retrieving"
                if self.route_after_validation(state) == "retry"
                else "reasoning"
            )
        if node_name == "retry":
            return "retrieving"
        if node_name == "reasoner":
            return "generating"
        return None

    # ========================================================
    # SYNC CONVENIENCE API
    # ========================================================

    def run_sync(
        self,
        query: str,
        *,
        context: (
            ConversationContext | None
        ) = None,
    ) -> AgentState:
        """
        Convenience cho CLI/test.

        FastAPI async endpoint sau này nên dùng:

            await workflow.run(query)
        """

        return asyncio.run(
            self.run(
                query,
                context=context,
            )
        )


# ============================================================
# MODULE-LEVEL FACTORY
# ============================================================


def _stage_event(stage: str) -> dict[str, str]:
    return {
        "type": "stage",
        "stage": stage,
        "message": PUBLIC_STAGE_MESSAGES[stage],
    }


def build_workflow() -> TravelAgentWorkflow:

    return TravelAgentWorkflow()
