from __future__ import annotations

from typing import TypedDict

from pipeline.agents.context import (
    ConversationContext,
)

from pipeline.agents.schemas import (
    AgentResponse,
    EvidenceItem,
    ExecutionPlan,
    ReasonerOutput,
    ToolObservation,
    ValidationResult,
)


class AgentState(TypedDict, total=False):
    """
    Shared LangGraph state.

    Đây là state contract giữa các node:

        planner
        executor
        validator
        reasoner
        synthesizer

    Không chứa implementation logic.
    """

    # ========================================================
    # INPUT
    # ========================================================

    query: str

    conversation_context: (
        ConversationContext
    )

    # ========================================================
    # PLANNER
    # ========================================================

    plan: ExecutionPlan

    # ========================================================
    # TOOL EXECUTION
    # ========================================================

    observations: list[
        ToolObservation
    ]

    # Chỉ RAG + WEB.
    # Weather / Routing / Budget vẫn nằm trong observations.
    research_evidence: list[
        EvidenceItem
    ]

    # ========================================================
    # VALIDATION
    # ========================================================

    validation: ValidationResult

    retry_count: int

    # ========================================================
    # REASONER
    # ========================================================

    reasoner_output: ReasonerOutput

    # ========================================================
    # FINAL RESPONSE
    # ========================================================

    response: AgentResponse
