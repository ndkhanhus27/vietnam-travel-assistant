from __future__ import annotations

import asyncio
import json
import sys
import unittest
import uuid
from collections.abc import AsyncIterator
from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.dependencies import get_travel_workflow
from app.api.sse import encode_sse
from app.db.models import User
from app.db.repositories.auth import AuthRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.session import AsyncSessionFactory, close_db
from app.main import app
from app.security.tokens import create_access_token
from pipeline.agents.context import ConversationContext
from pipeline.agents.executor import ToolExecutor
from pipeline.agents.schemas import (
    ExecutionPlan,
    Intent,
    RetrievalMode,
    SubTask,
    TaskStatus,
    ToolName,
    ToolObservation,
)
from test_chat_service import DeterministicWorkflow


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class StreamingDeterministicWorkflow(DeterministicWorkflow):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.stream_calls = 0

    async def stream(
        self,
        query: str,
        *,
        context: ConversationContext | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        self.stream_calls += 1
        yield "progress", {
            "type": "stage",
            "stage": "planning",
            "message": "Đang phân tích yêu cầu",
        }

        if not self.clarify:
            yield "progress", {
                "type": "stage",
                "stage": "retrieving",
                "message": "Đang tìm thông tin du lịch",
            }
            yield "progress", {
                "type": "tool",
                "tool": "weather",
                "task_id": "weather-1",
                "status": "started",
            }

        state = await self.run(query, context=context)

        if not self.clarify:
            yield "progress", {
                "type": "tool",
                "tool": "weather",
                "task_id": "weather-1",
                "status": "completed",
            }
            for stage, message in (
                ("validating", "Đang kiểm tra thông tin"),
                ("reasoning", "Đang sắp xếp thông tin"),
                ("generating", "Đang chuẩn bị câu trả lời"),
            ):
                yield "progress", {
                    "type": "stage",
                    "stage": stage,
                    "message": message,
                }
        else:
            yield "progress", {
                "type": "stage",
                "stage": "generating",
                "message": "Đang chuẩn bị câu trả lời",
            }

        yield "result", state


class ToolProgressInstrumentationTest(unittest.IsolatedAsyncioTestCase):
    async def test_events_wrap_the_actual_registry_execution(self) -> None:
        calls: list[str] = []
        events: list[dict[str, Any]] = []

        class Registry:
            def execute(self, task, *, research_depth):
                calls.append(task.task_id)
                return ToolObservation(
                    task_id=task.task_id,
                    tool=task.tool,
                    status=TaskStatus.SUCCESS,
                )

        plan = ExecutionPlan(
            intent=Intent.ITINERARY,
            goal="Check weather",
            retrieval_mode=RetrievalMode.MIXED,
            subtasks=[
                SubTask(
                    task_id="weather-actual",
                    description="Check actual weather",
                    tool=ToolName.WEATHER,
                )
            ],
        )
        observations = await ToolExecutor(registry=Registry()).execute(
            plan,
            event_sink=events.append,
        )

        self.assertEqual(calls, ["weather-actual"])
        self.assertEqual(observations[0].status, TaskStatus.SUCCESS)
        self.assertEqual(
            [event["status"] for event in events],
            ["started", "completed"],
        )
        self.assertEqual(
            [event["task_id"] for event in events],
            ["weather-actual", "weather-actual"],
        )


class ChatSseIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.test_id = uuid.uuid4().hex
        self.email_prefix = f"chat-sse-{self.test_id}"
        async with AsyncSessionFactory.begin() as session:
            auth = AuthRepository(session)
            conversations = ConversationRepository(session)
            owner = await auth.create_user(
                email=f"{self.email_prefix}-owner@example.com"
            )
            other = await auth.create_user(
                email=f"{self.email_prefix}-other@example.com"
            )
            conversation = await conversations.create_conversation(
                user_id=owner.id
            )
            self.owner_id = owner.id
            self.other_id = other.id
            self.conversation_id = conversation.id

        self.owner_headers = self._headers(self.owner_id)
        self.other_headers = self._headers(self.other_id)
        self.workflow = StreamingDeterministicWorkflow(
            conversation_id=self.conversation_id
        )
        app.dependency_overrides[get_travel_workflow] = lambda: self.workflow
        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        app.dependency_overrides.clear()
        async with AsyncSessionFactory.begin() as session:
            await session.execute(
                delete(User).where(User.email.like(f"{self.email_prefix}%"))
            )
        await close_db()

    async def test_auth_validation_and_ownership_fail_before_stream(self) -> None:
        unauthorized = await self.client.post(
            self._path(),
            json={"content": "Xin chao"},
        )
        invalid = await self.client.post(
            self._path(),
            headers=self.owner_headers,
            json={"content": "   "},
        )
        foreign = await self.client.post(
            self._path(),
            headers=self.other_headers,
            json={"content": "Xin chao"},
        )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(self.workflow.calls, [])

        async with AsyncSessionFactory() as session:
            repository = ConversationRepository(session)
            messages = await repository.list_messages(
                self.conversation_id,
                self.owner_id,
            )
            runs = await repository.list_agent_runs_for_conversation(
                self.conversation_id,
                self.owner_id,
            )
        self.assertEqual(messages, [])
        self.assertEqual(runs, [])

    async def test_normal_stream_runs_once_and_persists_completed_payload(
        self,
    ) -> None:
        response, events = await self._stream("Lập lịch Đà Lạt 3 ngày")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.headers["cache-control"], "no-cache")
        self.assertEqual(response.headers["x-accel-buffering"], "no")

        names = [item["event"] for item in events]
        self.assertEqual(names[0], "connected")
        self.assertEqual(names[-1], "completed")
        self.assertNotIn("error", names)
        stages = [
            item["data"]["stage"]
            for item in events
            if item["event"] == "stage"
        ]
        self.assertEqual(
            stages,
            ["planning", "retrieving", "validating", "reasoning", "generating"],
        )
        tools = [item["data"] for item in events if item["event"] == "tool"]
        self.assertEqual(
            [item["status"] for item in tools],
            ["started", "completed"],
        )
        self.assertEqual([item["tool"] for item in tools], ["weather", "weather"])
        self.assertEqual(self.workflow.stream_calls, 1)
        self.assertEqual(len(self.workflow.calls), 1)

        completed = events[-1]["data"]
        self.assertEqual(completed["agent_run"]["status"], "success")
        self.assertEqual(completed["user_message"]["role"], "user")
        self.assertEqual(completed["assistant_message"]["role"], "assistant")
        citations = completed["assistant_message"]["citations"]
        self.assertEqual(citations[0]["evidence_id"], "evidence-1")
        self.assertEqual(citations[1]["task_id"], "weather-1")
        self.assertIsNone(citations[1]["url"])

        history = await self.client.get(
            f"/api/v1/conversations/{self.conversation_id}/messages",
            headers=self.owner_headers,
        )
        self.assertEqual([item["role"] for item in history.json()], ["user", "assistant"])
        self.assertEqual(len(history.json()), 2)

    async def test_degraded_stream_completes_without_error(self) -> None:
        self.workflow.degraded = True
        _, events = await self._stream("Gợi ý lịch trình")
        self.assertEqual(events[-1]["event"], "completed")
        self.assertEqual(events[-1]["data"]["agent_run"]["status"], "degraded")
        self.assertNotIn("error", [item["event"] for item in events])

    async def test_failure_emits_safe_error_and_persists_failed_run(self) -> None:
        self.workflow.fail = True
        response, events = await self._stream("Thực hiện yêu cầu")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1], {
            "event": "error",
            "data": {
                "code": "CHAT_WORKFLOW_ERROR",
                "message": "Unable to complete the assistant response.",
            },
        })
        self.assertNotIn("provider secret", json.dumps(events))
        self.assertEqual(len(self.workflow.calls), 1)

        async with AsyncSessionFactory() as session:
            repository = ConversationRepository(session)
            messages = await repository.list_messages(
                self.conversation_id,
                self.owner_id,
            )
            runs = await repository.list_agent_runs_for_conversation(
                self.conversation_id,
                self.owner_id,
            )
        self.assertEqual([item.role for item in messages], ["user"])
        self.assertEqual(runs[0].status, "failed")
        self.assertIsNone(runs[0].assistant_message_id)

    async def test_pending_context_is_restored_for_streaming_turn(self) -> None:
        self.workflow.clarify = True
        first = await self.client.post(
            f"/api/v1/conversations/{self.conversation_id}/messages",
            headers=self.owner_headers,
            json={"content": "Lập lịch Đà Lạt"},
        )
        self.assertEqual(first.status_code, 200)

        self.workflow.clarify = False
        _, events = await self._stream("3 ngày, khoảng 6 triệu cho 2 người")
        self.assertEqual(events[-1]["event"], "completed")
        restored = self.workflow.calls[1][1]
        self.assertIsNotNone(restored.pending_clarification)
        self.assertEqual(restored.pending_clarification.original_query, "Lập lịch Đà Lạt")

    async def test_encoder_preserves_vietnamese_and_openapi_documents_sse(
        self,
    ) -> None:
        encoded = encode_sse("stage", {"message": "Đang tìm thông tin du lịch"})
        self.assertEqual(
            encoded,
            'event: stage\ndata: {"message":"Đang tìm thông tin du lịch"}\n\n',
        )
        self.assertEqual(
            json.loads(encoded.split("data: ", 1)[1]),
            {"message": "Đang tìm thông tin du lịch"},
        )

        schema = (await self.client.get("/openapi.json")).json()
        operation = schema["paths"][
            "/api/v1/conversations/{conversation_id}/messages/stream"
        ]["post"]
        self.assertIn("security", operation)
        self.assertIn("text/event-stream", operation["responses"]["200"]["content"])

    async def _stream(self, content: str):
        async with self.client.stream(
            "POST",
            self._path(),
            headers=self.owner_headers,
            json={"content": content},
        ) as response:
            raw = "".join([chunk async for chunk in response.aiter_text()])
            return response, _parse_sse(raw)

    def _path(self) -> str:
        return f"/api/v1/conversations/{self.conversation_id}/messages/stream"

    @staticmethod
    def _headers(user_id: uuid.UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _parse_sse(payload: str) -> list[dict[str, Any]]:
    frames = payload.replace("\r\n", "\n").strip().split("\n\n")
    events: list[dict[str, Any]] = []
    for frame in frames:
        if not frame:
            continue
        fields = {}
        for line in frame.splitlines():
            key, value = line.split(": ", 1)
            fields[key] = value
        events.append(
            {
                "event": fields["event"],
                "data": json.loads(fields["data"]),
            }
        )
    return events


if __name__ == "__main__":
    unittest.main()
