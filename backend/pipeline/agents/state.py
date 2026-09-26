from __future__ import annotations

from typing import TypedDict

from pipeline.agents.schemas import (
    AgentResponse,
    EvidenceItem,
    ExecutionPlan,
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
    # REASONING
    # ========================================================

    reasoning_context: str

    # ========================================================
    # FINAL RESPONSE
    # ========================================================

    response: AgentResponse