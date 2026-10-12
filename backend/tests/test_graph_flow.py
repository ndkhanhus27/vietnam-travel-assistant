from types import SimpleNamespace
import unittest

from pipeline.agents.context import ConversationContext, ConversationRole
from pipeline.agents.executor import ToolExecutor
from pipeline.agents.schemas import (
    AgentResponse, ClarificationField, ClarificationRequest, ExecutionPlan,
    Intent, ReasonerOutput, RequirementLevel, RetrievalMode, SubTask,
    TaskStatus, ToolName, ToolObservation, ValidationIssue, ValidationResult,
)
from pipeline.agents.workflow import TravelAgentWorkflow


class GraphFlowTest(unittest.IsolatedAsyncioTestCase):
    def graph(self, *, clarification=False, failures=()):
        calls = []
        task = SubTask(task_id="weather", description="Check weather", tool=ToolName.WEATHER,
                       arguments={"location": "Hue"})
        plan = ExecutionPlan(intent=Intent.WEATHER, goal="Check Hue weather", entities=["Hue"],
                             retrieval_mode=RetrievalMode.TOOL_ONLY, subtasks=[task])
        if clarification:
            plan = plan.model_copy(update={"subtasks": [], "clarification": ClarificationRequest(
                question="Which destination?", fields=[ClarificationField(key="destination",
                    question="Which destination?", requirement=RequirementLevel.BLOCKING)])})

        class Registry:
            def execute(self, task, **kwargs):
                calls.append("tool")
                return ToolObservation(task_id=task.task_id, tool=task.tool, status=TaskStatus.SUCCESS,
                                       data={"location": "Hue", "temperature": 25})

        class Validator:
            def validate(self, **kwargs):
                index = calls.count("validate")
                calls.append("validate")
                if index < len(failures):
                    return ValidationResult(valid=False, issues=[ValidationIssue(
                        code="TEST_FAILURE", message="Tool unavailable", task_id="weather",
                        recoverable=failures[index])])
                return ValidationResult(valid=True)

        def reason(**kwargs):
            calls.append("reason")
            return ReasonerOutput(answer_type="WEATHER", answer_goal=plan.goal)

        def synthesize(**kwargs):
            calls.append("synthesize")
            return AgentResponse(answer="Hue weather is ready", intent=Intent.WEATHER,
                                 degraded=not kwargs["validation"].valid)

        graph = TravelAgentWorkflow(planner=SimpleNamespace(plan=lambda *args, **kwargs: plan),
                executor=ToolExecutor(registry=Registry()), validator=Validator(),
                reasoner=SimpleNamespace(reason=reason),
                synthesizer=SimpleNamespace(synthesize=synthesize))
        return graph, calls

    async def test_success_runs_nodes_and_preserves_conversation_state(self):
        graph, calls = self.graph()
        context = ConversationContext()
        state = await graph.run("Hue weather?", context=context)
        self.assertEqual(calls, ["tool", "validate", "reason", "synthesize"])
        self.assertEqual(state["query"], "Hue weather?")
        self.assertEqual(state["observations"][0].task_id, "weather")
        self.assertEqual(state["retry_count"], 0)
        roles = [item.role for item in state["conversation_context"].recent_messages]
        self.assertEqual(roles[-2:], [ConversationRole.USER, ConversationRole.ASSISTANT])
        self.assertEqual(context.recent_messages, [])

    async def test_clarification_ends_before_tools_and_saves_pending_request(self):
        graph, calls = self.graph(clarification=True)
        state = await graph.run("Weather?")
        self.assertEqual(calls, [])
        self.assertIsNotNone(state["response"].clarification)
        self.assertIsNotNone(state["conversation_context"].pending_clarification)

    async def test_recoverable_failure_retries_then_finishes(self):
        graph, calls = self.graph(failures=(True,))
        state = await graph.run("Hue weather?")
        self.assertEqual(calls.count("tool"), 2)
        self.assertEqual(state["retry_count"], 1)
        self.assertTrue(state["validation"].valid)

    async def test_nonrecoverable_failure_returns_degraded_without_retry(self):
        graph, calls = self.graph(failures=(False,))
        state = await graph.run("Hue weather?")
        self.assertEqual(calls.count("tool"), 1)
        self.assertTrue(state["response"].degraded)
        self.assertEqual(state["retry_count"], 0)

    async def test_stream_emits_tool_progress_and_one_final_state(self):
        graph, _ = self.graph()
        events = [event async for event in graph.stream("Hue weather?")]
        self.assertEqual(sum(kind == "result" for kind, _ in events), 1)
        tools = [payload for kind, payload in events if kind == "progress" and payload["type"] == "tool"]
        self.assertEqual([event["status"] for event in tools], ["started", "completed"])
