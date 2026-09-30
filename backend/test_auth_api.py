from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.dependencies import get_google_verifier
from app.db.models import User
from app.db.session import AsyncSessionFactory, close_db
from app.main import app
from app.security.google import GoogleIdentity
from app.security.tokens import create_access_token


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class StubGoogleVerifier:
    def __init__(self) -> None:
        self.identity: GoogleIdentity | None = None
        self.credentials: list[str] = []

    async def verify(self, credential: str) -> GoogleIdentity:
        self.credentials.append(credential)
        if self.identity is None:
            raise AssertionError("Google identity was not configured")
        return self.identity


class AuthApiIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.test_id = uuid.uuid4().hex
        self.email_prefix = f"auth-api-{self.test_id}"
        self.google_verifier = StubGoogleVerifier()
        app.dependency_overrides[get_google_verifier] = (
            lambda: self.google_verifier
        )
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

    async def test_register_validation_duplicate_and_safe_response(self) -> None:
        email = self._email("register")
        response = await self._register(email)

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["user"]["email"], email)
        self.assertEqual(body["token_type"], "bearer")
        self.assertNotIn("password_hash", response.text)
        self.assertNotIn("token_hash", response.text)

        duplicate = await self._register(email.upper())
        self.assertEqual(duplicate.status_code, 409)

        invalid_password = await self._register(
            self._email("short"),
            password="short",
        )
        self.assertEqual(invalid_password.status_code, 422)

    async def test_login_success_and_generic_credential_failure(self) -> None:
        email = self._email("login")
        password = "valid-password"
        await self._register(email, password=password)

        success = await self.client.post(
            "/api/v1/auth/login",
            json={"email": email.upper(), "password": password},
        )
        self.assertEqual(success.status_code, 200)
        self.assertTrue(success.json()["access_token"])
        self.assertTrue(success.json()["refresh_token"])

        wrong = await self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
        unknown = await self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self._email("unknown"),
                "password": password,
            },
        )
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.json(), unknown.json())

    async def test_current_user_requires_valid_access_token(self) -> None:
        registered = await self._register(self._email("me"))
        body = registered.json()

        missing = await self.client.get("/api/v1/users/me")
        malformed = await self.client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        valid = await self.client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        expired_token = create_access_token(
            uuid.UUID(body["user"]["id"]),
            now=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        expired = await self.client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(malformed.status_code, 401)
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()["id"], body["user"]["id"])

    async def test_refresh_rotates_and_rejects_old_token(self) -> None:
        registered = await self._register(self._email("refresh"))
        old_refresh = registered.json()["refresh_token"]

        refreshed = await self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotEqual(
            refreshed.json()["refresh_token"],
            old_refresh,
        )

        reused = await self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        self.assertEqual(reused.status_code, 401)

    async def test_logout_is_idempotent_and_blocks_refresh(self) -> None:
        registered = await self._register(self._email("logout"))
        refresh_token = registered.json()["refresh_token"]
        payload = {"refresh_token": refresh_token}

        first = await self.client.post("/api/v1/auth/logout", json=payload)
        second = await self.client.post("/api/v1/auth/logout", json=payload)
        refresh = await self.client.post("/api/v1/auth/refresh", json=payload)

        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)
        self.assertEqual(refresh.status_code, 401)

    async def test_logout_all_revokes_every_session(self) -> None:
        email = self._email("logout-all")
        password = "valid-password"
        registered = await self._register(email, password=password)
        first = registered.json()
        logged_in = await self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        second = logged_in.json()

        logout_all = await self.client.post(
            "/api/v1/auth/logout-all",
            headers={"Authorization": f"Bearer {first['access_token']}"},
        )
        self.assertEqual(logout_all.status_code, 204)

        for refresh_token in (
            first["refresh_token"],
            second["refresh_token"],
        ):
            response = await self.client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )
            self.assertEqual(response.status_code, 401)

    async def test_google_route_delegates_to_verifier(self) -> None:
        email = self._email("google")
        self.google_verifier.identity = GoogleIdentity(
            subject=f"google-sub-{self.test_id}",
            email=email,
            email_verified=True,
            display_name="Google API User",
        )

        response = await self.client.post(
            "/api/v1/auth/google",
            json={"credential": "deterministic-google-credential"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["email"], email)
        self.assertEqual(
            self.google_verifier.credentials,
            ["deterministic-google-credential"],
        )

    async def test_local_cors_origin_is_allowed(self) -> None:
        response = await self.client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "http://localhost:5173",
        )

    async def _register(
        self,
        email: str,
        *,
        password: str = "valid-password",
    ):
        return await self.client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "display_name": "API Test",
            },
        )

    def _email(self, suffix: str) -> str:
        return f"{self.email_prefix}-{suffix}@example.com"


if __name__ == "__main__":
    unittest.main()
