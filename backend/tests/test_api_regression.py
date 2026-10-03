from __future__ import annotations

import asyncio
import json
import sys
import unittest
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.api.dependencies import get_google_verifier, get_travel_workflow
from app.db.models import AuthAccount, RefreshToken, User
from app.db.repositories.auth import AuthRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.session import AsyncSessionFactory, close_db
from app.main import app
from app.security.google import GoogleIdentity
from app.security.password import verify_password
from app.security.tokens import create_access_token
from pipeline.agents.context import ContextBuilder, ConversationContext, ConversationRole
from pipeline.agents.schemas import (
    AgentResponse,
    ExecutionPlan,
    Intent,
    ReasonerOutput,
    RetrievalMode,
)


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class StubGoogleVerifier:
    def __init__(self) -> None:
        self.identity: GoogleIdentity | None = None

    async def verify(self, credential: str) -> GoogleIdentity:
        if self.identity is None:
            raise AssertionError("Google identity was not configured")
        return self.identity


class DeterministicWorkflow:
    def __init__(self) -> None:
        self.context_builder = ContextBuilder(max_recent_messages=12)
        self.calls: list[tuple[str, ConversationContext]] = []

    async def run(
        self,
        query: str,
        *,
        context: ConversationContext | None = None,
    ) -> dict:
        context = context or ConversationContext()
        self.calls.append((query, context.model_copy(deep=True)))
        final_context = self.context_builder.append_message(
            context,
            role=ConversationRole.USER,
            content=query,
        )
        response = AgentResponse(
            answer="Lich trinh thu nghiem da san sang.",
            intent=Intent.ITINERARY,
        )
        final_context = self.context_builder.append_message(
            final_context,
            role=ConversationRole.ASSISTANT,
            content=response.answer,
        )
        return {
            "plan": ExecutionPlan(
                intent=Intent.ITINERARY,
                goal="Build a deterministic itinerary",
                retrieval_mode=RetrievalMode.MIXED,
            ),
            "response": response,
            "conversation_context": final_context,
            "reasoner_output": ReasonerOutput(
                answer_type="ITINERARY",
                answer_goal="Provide a deterministic answer",
            ),
            "observations": [],
            "retry_count": 0,
        }

    async def stream(
        self,
        query: str,
        *,
        context: ConversationContext | None = None,
    ):
        yield "progress", {
            "type": "stage",
            "stage": "planning",
            "message": "Dang lap ke hoach",
        }
        yield "result", await self.run(query, context=context)


class ProductionApiRegressionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.test_id = uuid.uuid4().hex
        self.email_prefix = f"regression-{self.test_id}"
        self.google_verifier = StubGoogleVerifier()
        self.workflow = DeterministicWorkflow()
        app.dependency_overrides[get_google_verifier] = (
            lambda: self.google_verifier
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

    async def test_health_is_lightweight(self) -> None:
        response = await self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(self.workflow.calls, [])

    async def test_local_auth_hashes_password_and_issues_session(self) -> None:
        email = self._email("local")
        password = "SecurePassword123!"
        registered = await self._register(email, password)

        self.assertEqual(registered.status_code, 201)
        body = registered.json()
        logged_in = await self.client.post(
            "/api/v1/auth/login",
            json={"email": email.upper(), "password": password},
        )
        me = await self.client.get(
            "/api/v1/users/me",
            headers=self._headers(body["access_token"]),
        )

        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["id"], body["user"]["id"])
        async with AsyncSessionFactory() as session:
            repository = AuthRepository(session)
            account = await repository.get_local_account_for_user(
                uuid.UUID(body["user"]["id"])
            )
        self.assertIsNotNone(account)
        self.assertNotEqual(account.password_hash, password)
        self.assertTrue(verify_password(account.password_hash, password))

    async def test_refresh_rotation_rejects_old_token(self) -> None:
        registered = await self._register(
            self._email("refresh"),
            "SecurePassword123!",
        )
        user_id = uuid.UUID(registered.json()["user"]["id"])
        old_token = registered.json()["refresh_token"]

        first = await self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_token},
        )
        new_token = first.json()["refresh_token"]
        second = await self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": new_token},
        )
        reused = await self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_token},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(new_token, old_token)
        self.assertEqual(reused.status_code, 401)
        async with AsyncSessionFactory() as session:
            active_count = await session.scalar(
                select(func.count())
                .select_from(RefreshToken)
                .where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        self.assertEqual(active_count, 1)

    async def test_google_links_existing_local_user(self) -> None:
        email = self._email("linked")
        password = "SecurePassword123!"
        local = await self._register(email, password)
        self.google_verifier.identity = self._google_identity(
            email.upper(),
            "linked-subject",
        )

        google = await self.client.post(
            "/api/v1/auth/google",
            json={"credential": "verified-google-credential"},
        )
        local_login = await self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )

        self.assertEqual(google.status_code, 200)
        self.assertEqual(google.json()["user"]["id"], local.json()["user"]["id"])
        self.assertEqual(local_login.status_code, 200)
        async with AsyncSessionFactory() as session:
            users = await session.scalar(
                select(func.count()).select_from(User).where(User.email == email)
            )
            accounts = (
                await session.execute(
                    select(AuthAccount.provider).where(
                        AuthAccount.user_id
                        == uuid.UUID(local.json()["user"]["id"])
                    )
                )
            ).scalars().all()
        self.assertEqual(users, 1)
        self.assertEqual(set(accounts), {"local", "google"})

    async def test_google_first_user_rejects_public_password_attachment(self) -> None:
        email = self._email("google-first")
        self.google_verifier.identity = self._google_identity(
            email,
            "google-first-subject",
        )
        google = await self.client.post(
            "/api/v1/auth/google",
            json={"credential": "verified-google-credential"},
        )
        attacked = await self._register(email.upper(), "AttackerPassword123!")

        self.assertEqual(google.status_code, 200)
        self.assertEqual(attacked.status_code, 409)
        async with AsyncSessionFactory() as session:
            repository = AuthRepository(session)
            user = await repository.get_user_by_email(email)
            local_account = await repository.get_local_account_for_user(user.id)
            user_count = await session.scalar(
                select(func.count()).select_from(User).where(User.email == email)
            )
        self.assertEqual(user_count, 1)
        self.assertIsNone(local_account)

    async def test_conversation_crud_is_owner_scoped(self) -> None:
        owner_id, other_id = await self._create_users("crud")
        owner_headers = self._user_headers(owner_id)
        other_headers = self._user_headers(other_id)

        created = await self.client.post(
            "/api/v1/conversations",
            headers=owner_headers,
            json={"title": "  Da Lat trip  "},
        )
        conversation_id = created.json()["id"]
        listed = await self.client.get(
            "/api/v1/conversations",
            headers=owner_headers,
        )
        fetched = await self.client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=owner_headers,
        )
        foreign = await self.client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=other_headers,
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["title"], "Da Lat trip")
        self.assertIn(conversation_id, [item["id"] for item in listed.json()])
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(foreign.status_code, 404)

    async def test_non_stream_chat_persists_messages_and_agent_run(self) -> None:
        owner_id, _ = await self._create_users("chat")
        conversation_id = await self._create_conversation(owner_id)

        response = await self.client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self._user_headers(owner_id),
            json={"content": "Lap lich Da Lat 3 ngay"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agent_run"]["status"], "success")
        async with AsyncSessionFactory() as session:
            repository = ConversationRepository(session)
            messages = await repository.list_messages(conversation_id, owner_id)
            runs = await repository.list_agent_runs_for_conversation(
                conversation_id,
                owner_id,
            )
        self.assertEqual([item.role for item in messages], ["user", "assistant"])
        self.assertEqual([item.sequence_no for item in messages], [1, 2])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "success")

    async def test_sse_exposes_only_public_event_contract(self) -> None:
        owner_id, _ = await self._create_users("sse")
        conversation_id = await self._create_conversation(owner_id)

        async with self.client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages/stream",
            headers=self._user_headers(owner_id),
            json={"content": "Lap lich Da Lat 3 ngay"},
        ) as response:
            payload = "".join([chunk async for chunk in response.aiter_text()])

        events = self._parse_sse(payload)
        event_names = [item["event"] for item in events]
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(event_names, ["connected", "stage", "completed"])
        self.assertEqual(events[1]["data"]["stage"], "planning")
        self.assertNotIn("node", payload)
        self.assertNotIn("chain_of_thought", payload)

    async def _register(self, email: str, password: str):
        return await self.client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "display_name": "Regression User",
            },
        )

    async def _create_users(self, suffix: str) -> tuple[uuid.UUID, uuid.UUID]:
        async with AsyncSessionFactory.begin() as session:
            repository = AuthRepository(session)
            owner = await repository.create_user(
                email=self._email(f"{suffix}-owner")
            )
            other = await repository.create_user(
                email=self._email(f"{suffix}-other")
            )
            return owner.id, other.id

    async def _create_conversation(self, user_id: uuid.UUID) -> uuid.UUID:
        async with AsyncSessionFactory.begin() as session:
            conversation = await ConversationRepository(session).create_conversation(
                user_id=user_id
            )
            return conversation.id

    def _email(self, suffix: str) -> str:
        return f"{self.email_prefix}-{suffix}@example.com"

    def _google_identity(self, email: str, suffix: str) -> GoogleIdentity:
        return GoogleIdentity(
            subject=f"{self.test_id}-{suffix}",
            email=email,
            email_verified=True,
            display_name="Google Regression User",
        )

    @staticmethod
    def _headers(access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    @staticmethod
    def _user_headers(user_id: uuid.UUID) -> dict[str, str]:
        return ProductionApiRegressionTest._headers(create_access_token(user_id))

    @staticmethod
    def _parse_sse(payload: str) -> list[dict]:
        events: list[dict] = []
        for frame in payload.replace("\r\n", "\n").strip().split("\n\n"):
            fields = {}
            for line in frame.splitlines():
                key, value = line.split(": ", 1)
                fields[key] = value
            events.append(
                {"event": fields["event"], "data": json.loads(fields["data"])}
            )
        return events


if __name__ == "__main__":
    unittest.main()
