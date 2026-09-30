from __future__ import annotations

import asyncio
import sys
import unittest
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api.dependencies import get_travel_workflow
from app.db.models import AgentRun, Conversation, Message, User
from app.db.repositories.auth import AuthRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.session import AsyncSessionFactory, close_db
from app.main import app
from app.security.tokens import create_access_token
from test_chat_service import DeterministicWorkflow


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class ConversationApiIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.test_id = uuid.uuid4().hex
        self.email_prefix = f"conversation-api-{self.test_id}"
        async with AsyncSessionFactory.begin() as session:
            auth = AuthRepository(session)
            owner = await auth.create_user(
                email=f"{self.email_prefix}-owner@example.com"
            )
            other = await auth.create_user(
                email=f"{self.email_prefix}-other@example.com"
            )
            self.owner_id = owner.id
            self.other_id = other.id

        self.owner_headers = self._headers(self.owner_id)
        self.other_headers = self._headers(self.other_id)
        self.workflow: DeterministicWorkflow | None = None
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

    async def test_create_requires_auth_and_normalizes_optional_title(
        self,
    ) -> None:
        unauthorized = await self.client.post("/api/v1/conversations", json={})
        self.assertEqual(unauthorized.status_code, 401)

        blank = await self._create()
        titled = await self._create("  Da Lat trip  ")
        self.assertEqual(blank.status_code, 201)
        self.assertIsNone(blank.json()["title"])
        self.assertEqual(titled.status_code, 201)
        self.assertEqual(titled.json()["title"], "Da Lat trip")
        self.assertNotIn("user_id", titled.json())
        self.assertNotIn("context_state", titled.json())

        async with AsyncSessionFactory() as session:
            conversation = await session.get(
                Conversation,
                uuid.UUID(titled.json()["id"]),
            )
            self.assertEqual(conversation.user_id, self.owner_id)

    async def test_list_is_owner_scoped_ordered_and_paginated(self) -> None:
        first = (await self._create("First")).json()
        second = (await self._create("Second")).json()
        await self.client.post(
            "/api/v1/conversations",
            headers=self.other_headers,
            json={"title": "Other user"},
        )

        response = await self.client.get(
            "/api/v1/conversations?limit=1&offset=0",
            headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [second["id"]])

        next_page = await self.client.get(
            "/api/v1/conversations?limit=1&offset=1",
            headers=self.owner_headers,
        )
        self.assertEqual(
            [item["id"] for item in next_page.json()],
            [first["id"]],
        )
        invalid = await self.client.get(
            "/api/v1/conversations?limit=101&offset=-1",
            headers=self.owner_headers,
        )
        self.assertEqual(invalid.status_code, 422)

    async def test_foreign_conversation_is_hidden_for_every_operation(
        self,
    ) -> None:
        conversation_id = (await self._create("Private")).json()["id"]
        paths = [
            ("get", f"/api/v1/conversations/{conversation_id}", None),
            (
                "patch",
                f"/api/v1/conversations/{conversation_id}",
                {"title": "Stolen"},
            ),
            ("delete", f"/api/v1/conversations/{conversation_id}", None),
            (
                "get",
                f"/api/v1/conversations/{conversation_id}/messages",
                None,
            ),
        ]
        for method, path, payload in paths:
            response = await self.client.request(
                method,
                path,
                headers=self.other_headers,
                json=payload,
            )
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "Conversation not found"})

        owned = await self.client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=self.owner_headers,
        )
        self.assertEqual(owned.status_code, 200)
        self.assertEqual(owned.json()["title"], "Private")

    async def test_patch_archive_and_explicit_field_semantics(self) -> None:
        conversation_id = (await self._create("Original")).json()["id"]
        path = f"/api/v1/conversations/{conversation_id}"

        archived = await self.client.patch(
            path,
            headers=self.owner_headers,
            json={"is_archived": True},
        )
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(archived.json()["title"], "Original")
        self.assertTrue(archived.json()["is_archived"])

        empty_patch = await self.client.patch(
            path,
            headers=self.owner_headers,
            json={},
        )
        self.assertEqual(empty_patch.status_code, 200)
        self.assertEqual(empty_patch.json()["title"], "Original")
        self.assertTrue(empty_patch.json()["is_archived"])

        default_list = await self.client.get(
            "/api/v1/conversations",
            headers=self.owner_headers,
        )
        included = await self.client.get(
            "/api/v1/conversations?include_archived=true",
            headers=self.owner_headers,
        )
        self.assertEqual(default_list.json(), [])
        self.assertEqual([item["id"] for item in included.json()], [conversation_id])

        renamed = await self.client.patch(
            path,
            headers=self.owner_headers,
            json={"title": "  Renamed  "},
        )
        self.assertEqual(renamed.json()["title"], "Renamed")
        self.assertTrue(renamed.json()["is_archived"])

    async def test_history_preserves_safe_message_payload(self) -> None:
        conversation_id = uuid.UUID((await self._create()).json()["id"])
        citations = [
            {
                "citation_id": "evidence-citation",
                "evidence_id": "evidence-1",
                "task_id": None,
                "title": "Travel source",
                "url": "https://example.com/travel",
                "source_type": "web",
                "tool": None,
                "provider": None,
                "metadata": {},
            },
            {
                "citation_id": "tool-citation",
                "evidence_id": None,
                "task_id": "weather-1",
                "title": "Weather data",
                "url": None,
                "source_type": "weather",
                "tool": "weather",
                "provider": "openweather",
                "metadata": {},
            },
        ]
        async with AsyncSessionFactory.begin() as session:
            repository = ConversationRepository(session)
            conversation = await repository.get_conversation_by_id(
                conversation_id,
                self.owner_id,
            )
            await repository.add_message(
                conversation_id=conversation_id,
                role="user",
                content="Question",
            )
            await repository.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content="Answer",
                intent="ITINERARY",
                citations=citations,
                warnings=["Forecast may change"],
            )
            await repository.update_conversation_context(
                conversation,
                {"private": "must not leak"},
            )

        response = await self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([item["sequence_no"] for item in body], [1, 2])
        self.assertEqual(body[1]["citations"], citations)
        self.assertEqual(body[1]["warnings"], ["Forecast may change"])
        self.assertNotIn("context_state", response.text)

    async def test_create_chat_history_and_delete_cascade(self) -> None:
        conversation_id = uuid.UUID((await self._create()).json()["id"])
        self.workflow = DeterministicWorkflow(conversation_id=conversation_id)
        chat = await self.client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self.owner_headers,
            json={"content": "Lap lich Da Lat"},
        )
        self.assertEqual(chat.status_code, 200)
        message_ids = [
            uuid.UUID(chat.json()["user_message"]["id"]),
            uuid.UUID(chat.json()["assistant_message"]["id"]),
        ]
        run_id = uuid.UUID(chat.json()["agent_run"]["id"])

        history = await self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self.owner_headers,
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(
            [item["role"] for item in history.json()],
            ["user", "assistant"],
        )

        deleted = await self.client.delete(
            f"/api/v1/conversations/{conversation_id}",
            headers=self.owner_headers,
        )
        self.assertEqual(deleted.status_code, 204)
        missing = await self.client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=self.owner_headers,
        )
        self.assertEqual(missing.status_code, 404)

        async with AsyncSessionFactory() as session:
            remaining_messages = (
                await session.execute(
                    select(Message).where(Message.id.in_(message_ids))
                )
            ).scalars().all()
            remaining_run = await session.get(AgentRun, run_id)
        self.assertEqual(remaining_messages, [])
        self.assertIsNone(remaining_run)

    async def test_openapi_contains_crud_history_and_hides_context(self) -> None:
        response = await self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        base = "/api/v1/conversations"
        item = f"{base}/{{conversation_id}}"
        messages = f"{item}/messages"
        self.assertTrue({"get", "post"}.issubset(schema["paths"][base]))
        self.assertTrue(
            {"get", "patch", "delete"}.issubset(schema["paths"][item])
        )
        self.assertTrue({"get", "post"}.issubset(schema["paths"][messages]))
        for path, methods in (
            (base, ("get", "post")),
            (item, ("get", "patch", "delete")),
            (messages, ("get",)),
        ):
            for method in methods:
                self.assertIn("security", schema["paths"][path][method])
        self.assertNotIn("context_state", str(schema["components"]["schemas"]))

    async def _create(self, title: str | None = None):
        payload = {} if title is None else {"title": title}
        return await self.client.post(
            "/api/v1/conversations",
            headers=self.owner_headers,
            json=payload,
        )

    @staticmethod
    def _headers(user_id: uuid.UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user_id)}"}


if __name__ == "__main__":
    unittest.main()
