from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.dependencies import get_redis, get_travel_workflow
from app.core.config import settings
from app.db.models import User
from app.db.repositories.auth import AuthRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.session import AsyncSessionFactory, close_db
from app.infra.redis import (
    RedisJsonCache,
    RedisLockManager,
    RedisRateLimiter,
    cache_key,
    lock_key,
    rate_limit_key,
)
from app.main import app
from app.security.password import hash_password
from app.security.tokens import create_access_token
from test_chat_service import DeterministicWorkflow


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class FakeRedis:
    def __init__(self, *, clock=lambda: 1_000.0, fail: bool = False) -> None:
        self.clock = clock
        self.fail = fail
        self.values: dict[str, tuple[str, float | None]] = {}
        self.closed = False

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis unavailable")

    def _read(self, key: str) -> str | None:
        stored = self.values.get(key)
        if stored is None:
            return None
        value, expires_at = stored
        if expires_at is not None and expires_at <= self.clock():
            self.values.pop(key, None)
            return None
        return value

    async def ping(self) -> bool:
        self._check()
        return True

    async def aclose(self) -> None:
        self.closed = True

    async def get(self, key: str) -> str | None:
        self._check()
        return self._read(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        self._check()
        if nx and self._read(key) is not None:
            return None
        expires_at = self.clock() + ex if ex is not None else None
        self.values[key] = (value, expires_at)
        return True

    async def delete(self, key: str) -> int:
        self._check()
        existed = self._read(key) is not None
        self.values.pop(key, None)
        return int(existed)

    async def eval(self, script: str, count: int, key: str, *args):
        self._check()
        if "INCR" in script:
            current = int(self._read(key) or 0) + 1
            ttl = int(args[0])
            stored = self.values.get(key)
            expires_at = stored[1] if stored is not None else None
            if current == 1 or expires_at is None:
                expires_at = self.clock() + ttl
            self.values[key] = (str(current), expires_at)
            return [current, max(int(expires_at - self.clock()), 1)]

        token = str(args[0])
        if self._read(key) == token:
            return await self.delete(key)
        return 0


class RedisPrimitiveTest(unittest.IsolatedAsyncioTestCase):
    async def test_key_generation_is_stable_normalized_and_namespaced(self) -> None:
        first = cache_key("weather", "  DA   LAT ", "2026-10-01")
        second = cache_key("weather", "da lat", "2026-10-01")
        different = cache_key("weather", "Hue", "2026-10-01")
        self.assertEqual(first, second)
        self.assertNotEqual(first, different)
        self.assertTrue(first.startswith("vta:cache:weather:"))
        self.assertTrue(rate_limit_key("chat", "user-a", 1).startswith(
            "vta:ratelimit:chat:"
        ))
        self.assertTrue(lock_key("index", "documents").startswith(
            "vta:lock:index:"
        ))

    async def test_rate_limit_counts_expires_and_isolates_identities(self) -> None:
        now = [1_000.0]
        client = FakeRedis(clock=lambda: now[0])
        limiter = RedisRateLimiter(client, clock=lambda: now[0])

        first = await limiter.check(
            scope="chat", identity="user-a", limit=2, window_seconds=60
        )
        second = await limiter.check(
            scope="chat", identity="user-a", limit=2, window_seconds=60
        )
        denied = await limiter.check(
            scope="chat", identity="user-a", limit=2, window_seconds=60
        )
        other = await limiter.check(
            scope="chat", identity="user-b", limit=2, window_seconds=60
        )
        self.assertTrue(first.allowed)
        self.assertEqual(first.remaining, 1)
        self.assertTrue(second.allowed)
        self.assertFalse(denied.allowed)
        self.assertGreater(denied.retry_after, 0)
        self.assertTrue(other.allowed)

        now[0] += 61
        reset = await limiter.check(
            scope="chat", identity="user-a", limit=2, window_seconds=60
        )
        self.assertTrue(reset.allowed)
        self.assertEqual(reset.remaining, 1)

    async def test_json_cache_round_trip_ttl_hit_and_fallback(self) -> None:
        now = [1_000.0]
        cache = RedisJsonCache(FakeRedis(clock=lambda: now[0]))
        key = cache_key("weather", "Hue", "tomorrow")
        calls = 0

        async def provider():
            nonlocal calls
            calls += 1
            return {"rain": False, "provider_calls": calls}

        first = await cache.get_or_set(key, provider, ttl_seconds=10)
        second = await cache.get_or_set(key, provider, ttl_seconds=10)
        self.assertEqual(first, second)
        self.assertEqual(calls, 1)

        now[0] += 11
        third = await cache.get_or_set(key, provider, ttl_seconds=10)
        self.assertEqual(third["provider_calls"], 2)
        self.assertEqual(calls, 2)

        failing_cache = RedisJsonCache(FakeRedis(fail=True))
        fallback = await failing_cache.get_or_set(
            key, provider, ttl_seconds=10
        )
        self.assertEqual(fallback["provider_calls"], 3)

    async def test_json_cache_serialization_and_delete(self) -> None:
        cache = RedisJsonCache(FakeRedis())
        key = cache_key("geocode", "Hoi An")
        value = {"lat": 15.88, "lon": 108.33, "labels": ["Hoi An"]}
        self.assertTrue(await cache.set_json(key, value, ttl_seconds=30))
        self.assertEqual(await cache.get_json(key), value)
        self.assertTrue(await cache.delete(key))
        self.assertIsNone(await cache.get_json(key))

    async def test_lock_release_requires_owner_token(self) -> None:
        client = FakeRedis()
        locks = RedisLockManager(client)
        key = lock_key("refresh", "account-1")
        token = await locks.acquire(key, ttl_seconds=10)
        self.assertIsNotNone(token)
        self.assertIsNone(await locks.acquire(key, ttl_seconds=10))
        self.assertFalse(await locks.release(key, "not-the-owner"))
        self.assertTrue(await locks.release(key, token or ""))


class RedisLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        settings.redis_enabled = False
        app.state.redis = None

    async def test_disabled_startup_keeps_redis_none(self) -> None:
        settings.redis_enabled = False
        with patch("pipeline.agents.workflow.build_workflow", return_value=object()):
            async with app.router.lifespan_context(app):
                self.assertIsNone(app.state.redis)

    async def test_enabled_startup_reuses_and_closes_shared_client(self) -> None:
        settings.redis_enabled = True
        client = FakeRedis()
        with (
            patch(
                "pipeline.agents.workflow.build_workflow",
                return_value=object(),
            ),
            patch("app.main.create_redis_client", AsyncMock(return_value=client)),
        ):
            async with app.router.lifespan_context(app):
                self.assertIs(app.state.redis, client)
        self.assertTrue(client.closed)

    async def test_unavailable_startup_degrades_with_warning(self) -> None:
        settings.redis_enabled = True
        with (
            patch(
                "pipeline.agents.workflow.build_workflow",
                return_value=object(),
            ),
            patch(
                "app.main.create_redis_client",
                AsyncMock(side_effect=ConnectionError("offline")),
            ),
            self.assertLogs("app.main", level="WARNING") as logs,
        ):
            async with app.router.lifespan_context(app):
                self.assertIsNone(app.state.redis)
        self.assertIn("Redis unavailable", " ".join(logs.output))


class RedisRateLimitApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_chat_limit = settings.rate_limit_chat_requests
        self.original_auth_limit = settings.rate_limit_auth_requests
        self.original_enabled = settings.rate_limit_enabled
        settings.rate_limit_enabled = True
        settings.rate_limit_chat_requests = 1
        settings.rate_limit_auth_requests = 2

        self.test_id = uuid.uuid4().hex
        self.email_prefix = f"redis-limit-{self.test_id}"
        async with AsyncSessionFactory.begin() as session:
            auth = AuthRepository(session)
            conversations = ConversationRepository(session)
            owner = await auth.create_user(
                email=f"{self.email_prefix}-owner@example.com"
            )
            account_user = await auth.create_user(
                email=f"{self.email_prefix}-account@example.com"
            )
            await auth.create_local_account(
                user_id=account_user.id,
                password_hash=hash_password("correct-password"),
            )
            conversation = await conversations.create_conversation(
                user_id=owner.id
            )
            self.owner_id = owner.id
            self.account_email = account_user.email
            self.conversation_id = conversation.id

        self.redis = FakeRedis()
        self.workflow = DeterministicWorkflow(
            conversation_id=self.conversation_id
        )
        app.dependency_overrides[get_redis] = lambda: self.redis
        app.dependency_overrides[get_travel_workflow] = lambda: self.workflow
        self.client = AsyncClient(
            transport=ASGITransport(
                app=app,
                client=("192.0.2.10", 12345),
            ),
            base_url="http://testserver",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        app.dependency_overrides.clear()
        settings.rate_limit_chat_requests = self.original_chat_limit
        settings.rate_limit_auth_requests = self.original_auth_limit
        settings.rate_limit_enabled = self.original_enabled
        async with AsyncSessionFactory.begin() as session:
            await session.execute(
                delete(User).where(User.email.like(f"{self.email_prefix}%"))
            )
        await close_db()

    async def test_chat_and_sse_are_limited_before_second_workflow(self) -> None:
        headers = {
            "Authorization": f"Bearer {create_access_token(self.owner_id)}"
        }
        normal = await self.client.post(
            f"/api/v1/conversations/{self.conversation_id}/messages",
            headers=headers,
            json={"content": "Plan a trip"},
        )
        streamed = await self.client.post(
            f"/api/v1/conversations/{self.conversation_id}/messages/stream",
            headers=headers,
            json={"content": "Plan another trip"},
        )
        self.assertEqual(normal.status_code, 200)
        self.assertEqual(streamed.status_code, 429)
        self.assertGreater(int(streamed.headers["retry-after"]), 0)
        self.assertFalse(streamed.headers["content-type"].startswith(
            "text/event-stream"
        ))
        self.assertEqual(len(self.workflow.calls), 1)

    async def test_invalid_login_is_normal_then_limited_per_ip(self) -> None:
        payload = {"email": self.account_email, "password": "wrong-password"}
        first = await self.client.post("/api/v1/auth/login", json=payload)
        unknown = await self.client.post(
            "/api/v1/auth/login",
            json={
                "email": f"{self.email_prefix}-missing@example.com",
                "password": "wrong-password",
            },
        )
        denied = await self.client.post("/api/v1/auth/login", json=payload)
        self.assertEqual(first.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(first.json(), unknown.json())
        self.assertEqual(denied.status_code, 429)

        other_client = AsyncClient(
            transport=ASGITransport(
                app=app,
                client=("198.51.100.20", 23456),
            ),
            base_url="http://testserver",
        )
        try:
            isolated = await other_client.post(
                "/api/v1/auth/login", json=payload
            )
        finally:
            await other_client.aclose()
        self.assertEqual(isolated.status_code, 401)

    async def test_redis_failure_fails_open_and_logs_warning(self) -> None:
        app.dependency_overrides[get_redis] = lambda: FakeRedis(fail=True)
        with self.assertLogs("app.api.dependencies", level="WARNING") as logs:
            response = await self.client.post(
                "/api/v1/auth/login",
                json={"email": self.account_email, "password": "wrong-password"},
            )
        self.assertEqual(response.status_code, 401)
        self.assertIn("request allowed", " ".join(logs.output))


if __name__ == "__main__":
    unittest.main()
