import json
import unittest
from types import SimpleNamespace

from pipeline.agents.schemas import (
    EvidenceItem, EvidenceSource, ExecutionPlan, Intent, ReasonerOutput,
    ReasonerPoint, ReasonerSection, RetrievalMode, TaskStatus, ToolName, ToolObservation,
    ValidationResult,
)
from pipeline.agents.synthesizer import TravelSynthesizer


class SynthesizerSourcesTest(unittest.TestCase):
    def synthesize(self, answer):
        runtime = SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text=json.dumps({
            "answer_markdown": answer, "suggested_followups": ["More detail? [99]"],
        })))
        reasoner = ReasonerOutput(
            answer_type="RECOMMENDATION", answer_goal="Explore Hue",
            sections=[ReasonerSection(heading="Hue", purpose="Recommend",
                points=[ReasonerPoint(text="Visit the citadel", evidence_ids=["hue-source", "hue-source"],
                                      observation_task_ids=["hue-weather"])])],
        )
        return TravelSynthesizer(llm_runtime=runtime).synthesize(
            query="Where can I go in Hue?",
            plan=ExecutionPlan(intent=Intent.RECOMMENDATION, goal="Explore Hue", retrieval_mode=RetrievalMode.MIXED),
            reasoner_output=reasoner,
            research_evidence=[
                EvidenceItem(evidence_id="hue-source", source_type=EvidenceSource.WEB,
                    title="Hue source", content="Visit the citadel", url="https://example.com/hue"),
                EvidenceItem(evidence_id="unselected-source", source_type=EvidenceSource.WEB,
                    title="Unused source", content="Unrelated content"),
            ],
            observations=[ToolObservation(task_id="hue-weather", tool=ToolName.WEATHER,
                status=TaskStatus.SUCCESS, data={"provider": "openweather", "rain": True})],
            validation=ValidationResult(valid=True),
        )

    def test_sources_are_built_without_model_markers(self):
        result = self.synthesize("Visit the citadel. Bring a raincoat.")
        self.assertEqual(result.answer, "Visit the citadel. Bring a raincoat.")
        self.assertEqual([item.citation_id for item in result.citations], ["1", "2"])
        self.assertEqual(result.citations[0].evidence_id, "hue-source")
        self.assertEqual(result.citations[0].url, "https://example.com/hue")
        self.assertEqual(result.citations[1].task_id, "hue-weather")
        self.assertEqual(result.used_tools, [ToolName.WEB_SEARCH, ToolName.WEATHER])
        self.assertFalse(result.degraded)

    def test_invented_markers_cannot_change_sources_or_degrade_answer(self):
        result = self.synthesize("Visit the citadel [[evidence:invented]]. Bring a raincoat [99].")
        self.assertEqual(result.answer, "Visit the citadel. Bring a raincoat.")
        self.assertEqual([item.evidence_id for item in result.citations], ["hue-source", None])
        self.assertEqual(result.suggested_followups, ["More detail?"])
        self.assertEqual(result.warnings, [])
        self.assertFalse(result.degraded)

    def test_incomplete_marker_does_not_leak_an_internal_id(self):
        self.assertEqual(TravelSynthesizer._strip_source_markers("Visit Hue [[evidence:invented"), "Visit Hue")

    def test_model_cannot_replace_a_source_url(self):
        result = self.synthesize("Visit [Hue](https://invented.invalid).")
        self.assertEqual(result.answer, "Visit Hue.")
        self.assertEqual(result.citations[0].url, "https://example.com/hue")
        self.assertFalse(result.degraded)
