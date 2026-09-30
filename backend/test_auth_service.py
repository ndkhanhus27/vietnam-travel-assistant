from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from argon2 import PasswordHasher, Type
from sqlalchemy import delete, select

from app.db.models import AuthAccount, RefreshToken, User
from app.db.repositories.auth import AuthRepository
from app.db.session import AsyncSessionFactory, close_db
from app.security.password import needs_rehash, verify_password
from app.security.tokens import decode_access_token, hash_refresh_token
from app.services.auth import (
    AuthService,
    EmailAlreadyRegisteredError,
    ExpiredRefreshTokenError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidEmailError,
    InvalidRefreshTokenError,
    PasswordPolicyError,
    UserNotFoundError,
)


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class AuthServiceIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.test_id = uuid.uuid4().hex
        self.email_prefix = f"auth-service-{self.test_id}"
        self.now = datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc)

    async def asyncTearDown(self) -> None:
        async with AsyncSessionFactory.begin() as session:
            await session.execute(
                delete(User).where(User.email.like(f"{self.email_prefix}%"))
            )
        await close_db()

    async def test_register_persists_secure_normalized_credentials(self) -> None:
        email = self._email("register")
        password = "correct horse battery staple"

        async with AsyncSessionFactory() as session:
            service = self._service(session)
            result = await service.register(
                f"  {email.upper()}  ",
                password,
                display_name="Integration Test",
            )

            self.assertEqual(result.user.email, email)
            self.assertFalse(result.user.is_verified)
            self.assertEqual(result.access_token_expires_in, 15 * 60)
            claims = decode_access_token(result.access_token, now=self.now)
            self.assertEqual(claims.user_id, result.user.id)

            account = await service.repository.get_local_account_for_user(
                result.user.id
            )
            self.assertIsNotNone(account)
            self.assertNotEqual(account.password_hash, password)
            self.assertTrue(verify_password(account.password_hash, password))

            stored_token = (
                await service.repository.get_refresh_token_by_hash(
                    hash_refresh_token(result.refresh_token)
                )
            )
            self.assertIsNotNone(stored_token)
            self.assertNotEqual(stored_token.token_hash, result.refresh_token)

    async def test_duplicate_registration_is_rejected(self) -> None:
        email = self._email("duplicate")
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            await service.register(email, "first-password")

            with self.assertRaises(EmailAlreadyRegisteredError):
                await service.register(f" {email.upper()} ", "second-password")

    async def test_registration_validates_email_and_password_policy(self) -> None:
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            with self.assertRaises(InvalidEmailError):
                await service.register("not-an-email", "valid-password")
            with self.assertRaises(PasswordPolicyError):
                await service.register(self._email("short"), "short")
            with self.assertRaises(PasswordPolicyError):
                await service.register(self._email("long"), "x" * 129)

    async def test_login_success_and_generic_invalid_credentials(self) -> None:
        email = self._email("login")
        password = "valid-password"
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            registered = await service.register(email, password)
            logged_in = await service.login(email.upper(), password)

            self.assertEqual(logged_in.user.id, registered.user.id)
            self.assertNotEqual(
                logged_in.refresh_token,
                registered.refresh_token,
            )

            with self.assertRaises(InvalidCredentialsError):
                await service.login(email, "wrong-password")
            with self.assertRaises(InvalidCredentialsError):
                await service.login(self._email("unknown"), password)
            with self.assertRaises(InvalidCredentialsError):
                await service.login("not-an-email", password)

    async def test_login_rehashes_an_outdated_password_hash(self) -> None:
        email = self._email("rehash")
        password = "valid-password"
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            registered = await service.register(email, password)
            account = await service.repository.get_local_account_for_user(
                registered.user.id
            )
            weaker_hasher = PasswordHasher(
                time_cost=1,
                memory_cost=8_192,
                parallelism=1,
                hash_len=16,
                salt_len=16,
                type=Type.ID,
            )
            account.password_hash = weaker_hasher.hash(password)
            await session.commit()
            self.assertTrue(needs_rehash(account.password_hash))

            await service.login(email, password)

            self.assertFalse(needs_rehash(account.password_hash))
            self.assertTrue(verify_password(account.password_hash, password))

    async def test_get_user_returns_active_user_and_rejects_unknown_id(
        self,
    ) -> None:
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            registered = await service.register(
                self._email("get-user"),
                "valid-password",
            )

            loaded_user = await service.get_user(registered.user.id)
            self.assertEqual(loaded_user.id, registered.user.id)
            with self.assertRaises(UserNotFoundError):
                await service.get_user(uuid.uuid4())

    async def test_inactive_user_cannot_login_or_be_loaded(self) -> None:
        email = self._email("inactive")
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            registered = await service.register(email, "valid-password")
            user_id = registered.user.id
            await service.repository.set_user_active(registered.user, False)
            await session.commit()

            with self.assertRaises(InactiveUserError):
                await service.login(email, "valid-password")
            with self.assertRaises(InactiveUserError):
                await service.get_user(user_id)

    async def test_refresh_rotates_and_rejects_reuse(self) -> None:
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            registered = await service.register(
                self._email("refresh"),
                "valid-password",
            )
            old_hash = hash_refresh_token(registered.refresh_token)
            refreshed = await service.refresh(registered.refresh_token)

            self.assertNotEqual(
                refreshed.refresh_token,
                registered.refresh_token,
            )
            old_token = await service.repository.get_refresh_token_by_hash(
                old_hash
            )
            new_token = await service.repository.get_refresh_token_by_hash(
                hash_refresh_token(refreshed.refresh_token)
            )
            self.assertEqual(old_token.revoked_at, self.now)
            self.assertEqual(old_token.last_used_at, self.now)
            self.assertEqual(old_token.replaced_by_token_id, new_token.id)

            with self.assertRaises(InvalidRefreshTokenError):
                await service.refresh(registered.refresh_token)

    async def test_expired_refresh_token_is_rejected(self) -> None:
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            registered = await service.register(
                self._email("expired"),
                "valid-password",
            )
            stored_token = (
                await service.repository.get_refresh_token_by_hash(
                    hash_refresh_token(registered.refresh_token)
                )
            )
            stored_token.expires_at = self.now - timedelta(seconds=1)
            await session.commit()

            with self.assertRaises(ExpiredRefreshTokenError):
                await service.refresh(registered.refresh_token)

    async def test_logout_is_idempotent(self) -> None:
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            registered = await service.register(
                self._email("logout"),
                "valid-password",
            )
            await service.logout(registered.refresh_token)
            await service.logout(registered.refresh_token)
            await service.logout("unknown-refresh-token")

            stored_token = (
                await service.repository.get_refresh_token_by_hash(
                    hash_refresh_token(registered.refresh_token)
                )
            )
            self.assertEqual(stored_token.revoked_at, self.now)

    async def test_logout_all_revokes_every_active_session(self) -> None:
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            registered = await service.register(
                self._email("logout-all"),
                "valid-password",
            )
            second_session = await service.login(
                registered.user.email,
                "valid-password",
            )

            self.assertEqual(await service.logout_all(registered.user.id), 2)
            result = await session.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == registered.user.id
                )
            )
            tokens = list(result.scalars())
            self.assertEqual(len(tokens), 2)
            self.assertTrue(all(token.revoked_at == self.now for token in tokens))

    async def test_registration_rolls_back_after_constraint_failure(self) -> None:
        email = self._email("rollback")
        async with AsyncSessionFactory() as session:
            service = self._service(session)
            with patch(
                "app.services.auth.hash_password",
                return_value="x" * 256,
            ):
                with self.assertRaises(Exception):
                    await service.register(email, "valid-password")

            self.assertIsNone(await service.repository.get_user_by_email(email))
            result = await session.execute(
                select(AuthAccount).join(User).where(User.email == email)
            )
            self.assertIsNone(result.scalar_one_or_none())

    def _email(self, suffix: str) -> str:
        return f"{self.email_prefix}-{suffix}@example.com"

    def _service(self, session) -> AuthService:
        return AuthService(session, clock=lambda: self.now)


if __name__ == "__main__":
    unittest.main()
