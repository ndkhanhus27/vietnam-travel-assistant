from __future__ import annotations

import unittest

from pipeline.agents.context import ActiveTask, ConversationContext, PendingClarification
from pipeline.agents.planner import PlannerDraft, TravelPlanner
from pipeline.agents.reasoner import TravelReasoner
from pipeline.agents.schemas import (
    ClarificationField,
    ClarificationRequest,
    ConstraintSource,
    EvidenceItem,
    EvidenceSource,
    ExtractedConstraint,
    Intent,
    ReasonerOutput,
    ReasonerPoint,
    ReasonerSection,
    RequirementLevel,
    ResearchDepth,
    ResponseModifier,
)


class StubPlanner(TravelPlanner):
    def __init__(self, drafts: dict[str, PlannerDraft]) -> None:
        super().__init__(llm_runtime=object())
        self.drafts = drafts

    def _analyze_with_gemini(self, query: str, *, context=None) -> PlannerDraft:
        return self.drafts[query]


def constraint(key: str, value: object) -> ExtractedConstraint:
    return ExtractedConstraint(
        key=key,
        value=value,
        source=ConstraintSource.CONVERSATION,
        explicit=True,
    )


def draft(
    intent: Intent,
    goal: str,
    *,
    entities: list[str] | None = None,
    constraints: list[dict] | None = None,
) -> PlannerDraft:
    return PlannerDraft(
        intent=intent,
        goal=goal,
        entities=entities or [],
        constraints=constraints or [],
        needs_travel_knowledge=intent
        in {
            Intent.FACTUAL_TRAVEL,
            Intent.RECOMMENDATION,
            Intent.COMPARISON,
            Intent.ITINERARY,
        },
    )


class WorkflowRegressionTest(unittest.TestCase):
    def test_pending_clarification_resumes_original_itinerary(self) -> None:
        query = "Da Lat"
        planner = StubPlanner(
            {
                query: draft(
                    Intent.FACTUAL_TRAVEL,
                    "Describe Da Lat",
                    entities=["Da Lat"],
                    constraints=[{"key": "destination", "value": "Da Lat"}],
                )
            }
        )
        pending = PendingClarification(
            original_query="Lap lich 3 ngay cho toi.",
            original_goal="Build a three-day itinerary",
            original_intent=Intent.ITINERARY,
            original_entities=[],
            request=ClarificationRequest(
                question="Ban muon di dau?",
                fields=[
                    ClarificationField(
                        key="destination",
                        question="Ban muon di dau?",
                        requirement=RequirementLevel.BLOCKING,
                    )
                ],
            ),
            known_constraints=[constraint("trip_duration_days", 3)],
        )

        plan = planner.plan(
            query,
            context=ConversationContext(
                pending_clarification=pending,
                known_constraints=[constraint("trip_duration_days", 3)],
            ),
        )

        self.assertEqual(plan.intent, Intent.ITINERARY)
        self.assertEqual(plan.entities, ["Da Lat"])
        values = {item.key: item.value for item in plan.constraints}
        self.assertEqual(values["destination"], "Da Lat")
        self.assertEqual(values["trip_duration_days"], 3)

    def test_response_modifier_preserves_task_and_destination(self) -> None:
        query = "dài hơn"
        active = ActiveTask(
            query="Goi y dia diem o Da Nang",
            intent=Intent.RECOMMENDATION,
            goal="Recommend places in Da Nang",
            entities=["Da Nang"],
            constraints=[constraint("destination", "Da Nang")],
            research_depth=ResearchDepth.ENRICHED,
            previous_answer="Ba goi y ngan.",
            research_evidence=[
                EvidenceItem(
                    evidence_id="rag_context",
                    source_type=EvidenceSource.RAG,
                    title="Da Nang travel source",
                    content="Grounded suggestions for Da Nang.",
                    entity="Da Nang",
                    score=0.9,
                )
            ],
        )
        planner = StubPlanner(
            {query: draft(Intent.GENERAL, "Expand the previous answer")}
        )

        plan = planner.plan(
            query,
            context=ConversationContext(active_task=active),
        )

        self.assertEqual(plan.intent, Intent.RECOMMENDATION)
        self.assertEqual(plan.entities, ["Da Nang"])
        self.assertEqual(plan.response_modifier, ResponseModifier.EXPAND)
        self.assertEqual(plan.retrieval_mode.value, "DIRECT")
        self.assertEqual(plan.subtasks, [])

    def test_citation_ids_accept_known_and_reject_unknown_evidence(self) -> None:
        evidence = [
            EvidenceItem(
                evidence_id="rag_1",
                source_type=EvidenceSource.RAG,
                title="Travel source",
                content="Grounded travel information.",
                score=0.9,
            )
        ]
        valid = ReasonerOutput(
            answer_type="RECOMMENDATION",
            answer_goal="Recommend a place",
            sections=[
                ReasonerSection(
                    heading="Suggestion",
                    purpose="Answer the request",
                    points=[
                        ReasonerPoint(
                            text="A grounded option",
                            evidence_ids=["rag_1"],
                        )
                    ],
                )
            ],
        )
        TravelReasoner._validate_references(
            output=valid,
            evidence=evidence,
            observations=[],
        )

        invalid = valid.model_copy(deep=True)
        invalid.sections[0].points[0].evidence_ids = ["unknown"]
        with self.assertRaisesRegex(ValueError, "unknown evidence_id"):
            TravelReasoner._validate_references(
                output=invalid,
                evidence=evidence,
                observations=[],
            )


if __name__ == "__main__":
    unittest.main()
