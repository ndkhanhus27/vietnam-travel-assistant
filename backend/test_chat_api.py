from __future__ import annotations

import asyncio
import sys
import unittest
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.dependencies import get_travel_workflow
from app.db.models import User
from app.db.repositories.auth import AuthRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.session import AsyncSessionFactory, close_db
from app.main import app
from app.security.tokens import create_access_token
from test_chat_service import DeterministicWorkflow


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class ChatApiIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.test_id = uuid.uuid4().hex
        self.email_prefix = f"chat-api-{self.test_id}"

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
        self.workflow = DeterministicWorkflow(
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

    async def test_auth_success_persistence_citations_and_single_run(
        self,
    ) -> None:
        path = self._path()
        unauthorized = await self.client.post(
            path,
            json={"content": "Lap lich Da Lat"},
        )
        self.assertEqual(unauthorized.status_code, 401)

        response = await self.client.post(
            path,
            headers=self.owner_headers,
            json={"content": "  Lap lich Da Lat 3 ngay  "},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["conversation_id"], str(self.conversation_id))
        self.assertEqual(body["user_message"]["role"], "user")
        self.assertEqual(body["user_message"]["content"], "Lap lich Da Lat 3 ngay")
        self.assertEqual(body["assistant_message"]["role"], "assistant")
        self.assertEqual(body["agent_run"]["status"], "success")
        self.assertEqual(len(self.workflow.calls), 1)

        citations = body["assistant_message"]["citations"]
        self.assertEqual(citations[0]["evidence_id"], "evidence-1")
        self.assertEqual(citations[1]["task_id"], "weather-1")
        self.assertIsNone(citations[1]["url"])

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
        self.assertEqual([item.role for item in messages], ["user", "assistant"])
        self.assertEqual([item.sequence_no for item in messages], [1, 2])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "success")

    async def test_non_owner_gets_same_not_found_without_writes(self) -> None:
        response = await self.client.post(
            self._path(),
            headers=self.other_headers,
            json={"content": "Xin chao"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Conversation not found"})
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

    async def test_request_validation_rejects_invalid_content(self) -> None:
        for content in ("", "   ", "x" * 10_001):
            response = await self.client.post(
                self._path(),
                headers=self.owner_headers,
                json={"content": content},
            )
            self.assertEqual(response.status_code, 422)

        injected_identity = await self.client.post(
            self._path(),
            headers=self.owner_headers,
            json={"content": "Xin chao", "user_id": str(self.other_id)},
        )
        self.assertEqual(injected_identity.status_code, 422)
        self.assertEqual(self.workflow.calls, [])

    async def test_degraded_response_is_http_success(self) -> None:
        self.workflow.degraded = True
        response = await self.client.post(
            self._path(),
            headers=self.owner_headers,
            json={"content": "Goi y lich trinh"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agent_run"]["status"], "degraded")
        self.assertTrue(response.json()["assistant_message"]["content"])

    async def test_workflow_failure_returns_safe_502_and_keeps_user_turn(
        self,
    ) -> None:
        self.workflow.fail = True
        response = await self.client.post(
            self._path(),
            headers=self.owner_headers,
            json={"content": "Thuc hien yeu cau"},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {"detail": "Unable to complete the assistant response."},
        )
        self.assertNotIn("provider secret", response.text)
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

    async def test_persisted_clarification_is_restored_next_request(self) -> None:
        self.workflow.clarify = True
        first = await self.client.post(
            self._path(),
            headers=self.owner_headers,
            json={"content": "Lap lich Da Lat"},
        )
        self.assertEqual(first.status_code, 200)

        self.workflow.clarify = False
        second = await self.client.post(
            self._path(),
            headers=self.owner_headers,
            json={"content": "3 ngay, khoang 6 trieu"},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self.workflow.calls), 2)
        restored = self.workflow.calls[1][1]
        self.assertIsNotNone(restored.pending_clarification)
        self.assertEqual(
            restored.pending_clarification.original_query,
            "Lap lich Da Lat",
        )

    async def test_openapi_documents_route_and_bearer_security(self) -> None:
        response = await self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        operation = response.json()["paths"][
            "/api/v1/conversations/{conversation_id}/messages"
        ]["post"]
        self.assertEqual(operation["tags"], ["chat"])
        self.assertIn("security", operation)

    def _path(self) -> str:
        return f"/api/v1/conversations/{self.conversation_id}/messages"

    @staticmethod
    def _headers(user_id: uuid.UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user_id)}"}


if __name__ == "__main__":
    unittest.main()
