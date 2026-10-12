from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from pipeline.agents.schemas import EvidenceItem, EvidenceSource, SubTask, TaskStatus, ToolName, ToolObservation
from pipeline.agents.tools.registry import ToolRegistry


class ToolContractTest(unittest.TestCase):
    def test_web_dispatch_preserves_focused_query_and_evidence(self):
        evidence = EvidenceItem(evidence_id="web_event", source_type=EvidenceSource.WEB,
                                title="Hue event", content="Hue event date", url="https://example.com/event")
        search = Mock(return_value=[evidence])
        registry = ToolRegistry(web_tool=SimpleNamespace(search=search))
        task = SubTask(task_id="event", description="Events", tool=ToolName.WEB_SEARCH,
                       arguments={"query": "Hue events October 2026", "entity": "Hue"})
        result = registry.execute(task)
        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.evidence, [evidence])
        search.assert_called_once_with(query=task.arguments["query"], entity="Hue")

    def test_web_exception_becomes_failed_observation(self):
        registry = ToolRegistry(web_tool=SimpleNamespace(search=Mock(side_effect=TimeoutError("offline"))))
        result = registry.execute(SubTask(task_id="web", description="Events", tool=ToolName.WEB_SEARCH,
                                         arguments={"query": "Hue events"}))
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.evidence, [])

    def test_invalid_weather_is_rejected_before_provider_call(self):
        execute = Mock()
        registry = ToolRegistry()
        registry._weather = SimpleNamespace(execute=execute)
        result = registry.execute(SubTask(task_id="rain", description="Weather", tool=ToolName.WEATHER,
                                         arguments={"location": "Hue"}))
        self.assertEqual(result.status, TaskStatus.FAILED)
        execute.assert_not_called()
