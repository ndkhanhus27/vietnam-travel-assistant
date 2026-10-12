from datetime import date
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pipeline.agents.planner import PlannerDraft, TravelPlanner, WebSearchDraft
from pipeline.agents.reasoner import TravelReasoner
from pipeline.agents.schemas import (
    EvidenceItem, EvidenceSource, Intent, ReasonerOutput, RetrievalMode,
    RoutingLocation, RoutingRequest, TaskStatus, ToolName, ToolObservation,
    WeatherMode, WeatherRequest,
    ValidationResult, ReasonerSection, ReasonerPoint,
)
from pipeline.agents.validator import AgentValidator
from pipeline.agents.tools.research_evidence import ResearchEvidenceAggregator


class CompoundPlanningTest(unittest.TestCase):
    def setUp(self):
        self.planner = TravelPlanner(llm_runtime=object())
        self.draft = PlannerDraft(
            intent=Intent.ITINERARY,
            goal="Hue itinerary with weather, events and routes",
            travel_knowledge_query="Hue three-day itinerary Dai Noi Khai Dinh",
            entities=["Hue", "Dai Noi", "Khai Dinh"],
            constraints=[{"key": "destination", "value": "Hue"},
                         {"key": "trip_duration_days", "value": 3}],
            web_search_requests=[WebSearchDraft(query="Hue events 17-18/10/2026", entity="Hue"),
                                 WebSearchDraft(query="Dai Noi opening hours October 2026", entity="Dai Noi")],
            weather_requests=[WeatherRequest(location=city, mode=WeatherMode.FORECAST_RANGE,
                              start_offset_days=1, end_offset_days=3,
                              time_expression="this weekend", original_query="Weekend rain?")
                              for city in ("Hue", "Da Nang")],
            routing_requests=[RoutingRequest(origin=RoutingLocation(query="Dai Noi Hue"),
                              destination=RoutingLocation(query=destination))
                              for destination in ("Khai Dinh Hue", "Thien Mu Hue")],
        )

    def plan(self):
        draft = self.planner._apply_deterministic_semantics(
            query="Plan Hue with events, rain and routes", draft=self.draft, context=None)
        with patch.object(TravelPlanner, "_local_today", return_value=date(2026, 10, 12)):
            return self.planner._build_execution_plan(query="Plan Hue with events, rain and routes", draft=draft)

    def test_compound_preserves_all_queries_locations_and_routes(self):
        plan = self.plan()
        self.assertIsNone(plan.clarification)
        self.assertEqual(plan.intent, Intent.ITINERARY)
        self.assertEqual(plan.retrieval_mode, RetrievalMode.MIXED)
        self.assertTrue(plan.is_compound)
        self.assertEqual(len(plan.subtasks), 7)
        self.assertEqual(plan.subtasks[0].arguments["query"], self.draft.travel_knowledge_query)
        web = [task for task in plan.subtasks if task.tool == ToolName.WEB_SEARCH]
        self.assertEqual([task.arguments["query"] for task in web],
                         [request.query for request in self.draft.web_search_requests])
        self.assertEqual(web[0].arguments["entity"], "Hue")
        weather = [task for task in plan.subtasks if task.tool == ToolName.WEATHER]
        self.assertEqual([task.arguments["location"] for task in weather], ["Hue", "Da Nang"])
        self.assertEqual([(task.arguments["start_offset_days"], task.arguments["end_offset_days"])
                          for task in weather], [(5, 6), (5, 6)])
        routes = [task for task in plan.subtasks if task.tool == ToolName.ROUTING]
        self.assertEqual(routes[0].arguments["destination"]["query"], "Khai Dinh Hue")
        self.assertEqual(next(c.value for c in plan.constraints if c.key == "destination"), "Hue")

    def test_web_failure_in_itinerary_is_not_masked_by_other_web_task(self):
        plan = self.plan()
        web = [task for task in plan.subtasks if task.tool == ToolName.WEB_SEARCH]
        evidence = EvidenceItem(evidence_id="web_hours", title="Hours", source_type=EvidenceSource.WEB,
                                content="Opening hours October 2026", url="https://example.com/hours")
        observations = [ToolObservation(task_id=web[0].task_id, tool=ToolName.WEB_SEARCH,
                                       status=TaskStatus.FAILED, error="No event evidence"),
                        ToolObservation(task_id=web[1].task_id, tool=ToolName.WEB_SEARCH,
                                       status=TaskStatus.SUCCESS, evidence=[evidence])]
        issues = AgentValidator._validate_current_info(plan=plan, observations=observations,
                                                      research_evidence=[evidence])
        self.assertEqual([issue.task_id for issue in issues], [web[0].task_id])

    def test_rag_web_fallback_cannot_satisfy_events(self):
        plan = self.plan()
        web = next(task for task in plan.subtasks if task.tool == ToolName.WEB_SEARCH)
        plan = plan.model_copy(update={"subtasks": [web]})
        evidence = EvidenceItem(evidence_id="web_attraction", title="Guide", source_type=EvidenceSource.WEB,
                                content="Travel guide 2026", url="https://example.com/guide")
        observation = ToolObservation(task_id=web.task_id, tool=ToolName.WEB_SEARCH,
                                      status=TaskStatus.SUCCESS, evidence=[])
        issues = AgentValidator._validate_current_info(plan=plan, observations=[observation],
                                                      research_evidence=[evidence])
        self.assertEqual(issues[0].code, "CURRENT_INFO_WEB_EVIDENCE_MISSING")

    def test_unanswered_compound_tasks_have_explicit_limitations(self):
        plan = self.plan()
        output = ReasonerOutput(answer_type="ITINERARY", answer_goal=plan.goal)
        output = TravelReasoner._enforce_compound_coverage(output, plan, [])
        self.assertTrue(output.degraded)
        self.assertEqual(len(output.sections), 6)
        self.assertIn("Hue events", " ".join(section.heading for section in output.sections))

    def test_weekend_offsets_on_sunday_and_next_weekend(self):
        request = self.draft.weather_requests[0]
        with patch.object(TravelPlanner, "_local_today", return_value=date(2026, 10, 18)):
            current = TravelPlanner._resolve_weather_dates(request)
            following = TravelPlanner._resolve_weather_dates(
                request.model_copy(update={"time_expression": "next weekend"}))
        self.assertEqual((current.start_offset_days, current.end_offset_days), (0, 0))
        self.assertEqual((following.start_offset_days, following.end_offset_days), (6, 7))

    def test_invalid_web_task_citation_is_repaired_once(self):
        plan = self.plan()
        web = next(task for task in plan.subtasks if task.tool == ToolName.WEB_SEARCH)
        invalid = ReasonerOutput(answer_type="ITINERARY", answer_goal=plan.goal,
                                 sections=[ReasonerSection(heading="Events", purpose="Limitation",
                                 points=[ReasonerPoint(text="Not verified",
                                         observation_task_ids=[web.task_id])])])
        corrected = ReasonerOutput(answer_type="ITINERARY", answer_goal=plan.goal)
        responses = iter([invalid, corrected])
        calls = []

        def generate_content(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text=next(responses).model_dump_json())

        reasoner = TravelReasoner(llm_runtime=SimpleNamespace(generate_content=generate_content))
        output = reasoner.reason(query="Plan with events", plan=plan, observations=[],
                                 research_evidence=[], validation=ValidationResult(valid=False))
        self.assertEqual(len(calls), 2)
        self.assertTrue(output.degraded)
        self.assertEqual(output.used_observation_task_ids, [])

    def test_relative_weekend_in_web_query_is_resolved_to_calendar_dates(self):
        with patch.object(TravelPlanner, "_local_today", return_value=date(2026, 10, 12)):
            query = TravelPlanner._resolve_search_dates("Hue events this weekend")
        self.assertEqual(query, "Hue events ngày 17/10/2026 đến 18/10/2026")

    def test_direct_web_queries_keep_evidence_when_entity_context_is_full(self):
        observations = []
        for index in range(4):
            evidence = EvidenceItem(evidence_id=f"web_{index}", title=f"Question {index}",
                                    source_type=EvidenceSource.WEB, entity="Hue",
                                    content=f"Independent current question {index}",
                                    url=f"https://example.com/{index}", score=0.5 + index / 10)
            observations.append(ToolObservation(task_id=f"task_{index}", tool=ToolName.WEB_SEARCH,
                                                status=TaskStatus.SUCCESS, evidence=[evidence]))
        selected = ResearchEvidenceAggregator(max_total=8, max_web_per_entity=2).aggregate(observations)
        self.assertEqual({item.evidence_id for item in selected}, {f"web_{index}" for index in range(4)})


if __name__ == "__main__":
    unittest.main()
