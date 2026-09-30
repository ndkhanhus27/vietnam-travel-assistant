from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError

from app.db.models import AuthAccount, User
from app.db.session import AsyncSessionFactory, close_db
from app.security.google import (
    GoogleAuthVerifier,
    GoogleIdentity,
    InvalidGoogleCredentialError,
    UnverifiedGoogleEmailError,
)
from app.security.password import verify_password
from app.security.tokens import decode_access_token, hash_refresh_token
from app.services.auth import AuthService, InactiveUserError


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class StubGoogleVerifier:
    def __init__(
        self,
        identity: GoogleIdentity | None = None,
        error: Exception | None = None,
    ) -> None:
        self.identity = identity
        self.error = error

    async def verify(self, credential: str) -> GoogleIdentity:
        if self.error is not None:
            raise self.error
        if self.identity is None:
            raise InvalidGoogleCredentialError("Invalid Google credential")
        return self.identity


class GoogleAuthVerifierUnitTest(unittest.IsolatedAsyncioTestCase):
    @patch("app.security.google.id_token.verify_oauth2_token")
    async def test_verified_claims_are_mapped_to_identity(self, verify) -> None:
        verify.return_value = {
            "sub": "google-subject",
            "email": "user@example.com",
            "email_verified": True,
            "name": "Google User",
            "picture": "https://example.com/avatar.jpg",
        }
        verifier = GoogleAuthVerifier(client_id="test-client-id")

        identity = await verifier.verify("signed-google-credential")

        self.assertEqual(identity.subject, "google-subject")
        self.assertEqual(identity.email, "user@example.com")
        self.assertTrue(identity.email_verified)
        call_args = verify.call_args.args
        self.assertEqual(call_args[0], "signed-google-credential")
        self.assertEqual(call_args[2], "test-client-id")

    @patch("app.security.google.id_token.verify_oauth2_token")
    async def test_library_failure_is_mapped_to_safe_error(self, verify) -> None:
        verify.side_effect = ValueError("low-level verification details")
        verifier = GoogleAuthVerifier(client_id="test-client-id")

        with self.assertRaisesRegex(
            InvalidGoogleCredentialError,
            "^Invalid Google credential$",
        ):
            await verifier.verify("invalid-credential")

    @patch("app.security.google.id_token.verify_oauth2_token")
    async def test_unverified_email_is_rejected(self, verify) -> None:
        verify.return_value = {
            "sub": "google-subject",
            "email": "user@example.com",
            "email_verified": False,
        }
        verifier = GoogleAuthVerifier(client_id="test-client-id")

        with self.assertRaises(UnverifiedGoogleEmailError):
            await verifier.verify("signed-google-credential")


class GoogleAuthIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.test_id = uuid.uuid4().hex
        self.email_prefix = f"google-auth-{self.test_id}"
        self.now = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)

    async def asyncTearDown(self) -> None:
        async with AsyncSessionFactory.begin() as session:
            await session.execute(
                delete(User).where(User.email.like(f"{self.email_prefix}%"))
            )
        await close_db()

    async def test_new_google_user_creates_account_and_app_session(self) -> None:
        identity = self._identity("new")
        async with AsyncSessionFactory() as session:
            service = self._service(session, identity)
            result = await service.login_with_google("verified-credential")

            self.assertEqual(result.user.email, identity.email)
            self.assertTrue(result.user.is_verified)
            claims = decode_access_token(result.access_token, now=self.now)
            self.assertEqual(claims.user_id, result.user.id)
            account = await service.repository.get_google_account(
                identity.subject
            )
            self.assertEqual(account.user_id, result.user.id)
            token = await service.repository.get_refresh_token_by_hash(
                hash_refresh_token(result.refresh_token)
            )
            self.assertIsNotNone(token)

    async def test_existing_google_subject_reuses_user_and_account(self) -> None:
        identity = self._identity("existing")
        async with AsyncSessionFactory() as session:
            service = self._service(session, identity)
            first = await service.login_with_google("first-credential")
            second = await service.login_with_google("second-credential")

            self.assertEqual(first.user.id, second.user.id)
            self.assertNotEqual(first.refresh_token, second.refresh_token)
            account_count = await session.scalar(
                select(func.count())
                .select_from(AuthAccount)
                .where(
                    AuthAccount.provider == "google",
                    AuthAccount.provider_user_id == identity.subject,
                )
            )
            self.assertEqual(account_count, 1)

    async def test_verified_email_links_existing_local_user(self) -> None:
        identity = self._identity("link", email_uppercase=True)
        password = "local-password"
        async with AsyncSessionFactory() as session:
            local_service = AuthService(
                session,
                clock=lambda: self.now,
                google_verifier=StubGoogleVerifier(identity),
            )
            local = await local_service.register(
                f"  {identity.email.upper()}  ",
                password,
            )
            local_account = (
                await local_service.repository.get_local_account_for_user(
                    local.user.id
                )
            )
            original_hash = local_account.password_hash
            user_count_before = await session.scalar(
                select(func.count()).select_from(User)
            )

            google = await local_service.login_with_google("credential")

            user_count_after = await session.scalar(
                select(func.count()).select_from(User)
            )
            self.assertEqual(google.user.id, local.user.id)
            self.assertEqual(user_count_after, user_count_before)
            self.assertEqual(local_account.password_hash, original_hash)
            self.assertTrue(verify_password(original_hash, password))
            accounts = await local_service.repository.list_auth_accounts_for_user(
                local.user.id
            )
            self.assertEqual({account.provider for account in accounts}, {
                "local",
                "google",
            })

    async def test_unverified_and_invalid_credentials_are_rejected(self) -> None:
        unverified = self._identity("unverified", verified=False)
        async with AsyncSessionFactory() as session:
            service = self._service(session, unverified)
            with self.assertRaises(UnverifiedGoogleEmailError):
                await service.login_with_google("credential")

            service.google_verifier = StubGoogleVerifier(
                error=InvalidGoogleCredentialError("invalid")
            )
            with self.assertRaises(InvalidGoogleCredentialError):
                await service.login_with_google("invalid-credential")

    async def test_inactive_google_user_is_rejected(self) -> None:
        identity = self._identity("inactive")
        async with AsyncSessionFactory() as session:
            service = self._service(session, identity)
            created = await service.login_with_google("credential")
            await service.repository.set_user_active(created.user, False)
            await session.commit()

            with self.assertRaises(InactiveUserError):
                await service.login_with_google("credential")

    async def test_profile_merge_fills_missing_and_preserves_local_values(
        self,
    ) -> None:
        missing_identity = self._identity("profile-missing")
        preserved_identity = self._identity("profile-preserved")
        async with AsyncSessionFactory() as session:
            missing_service = self._service(session, missing_identity)
            missing_local = await missing_service.register(
                missing_identity.email,
                "local-password",
            )
            filled = await missing_service.login_with_google("credential")
            self.assertEqual(filled.user.display_name, "Google User")
            self.assertEqual(filled.user.avatar_url, "https://example.com/a.jpg")
            self.assertTrue(filled.user.is_verified)

            preserved_service = self._service(session, preserved_identity)
            preserved_local = await preserved_service.register(
                preserved_identity.email,
                "local-password",
                display_name="Local Name",
            )
            preserved_local.user.avatar_url = "https://local.example/avatar.jpg"
            await session.commit()
            preserved = await preserved_service.login_with_google("credential")
            self.assertEqual(preserved.user.display_name, "Local Name")
            self.assertEqual(
                preserved.user.avatar_url,
                "https://local.example/avatar.jpg",
            )
            self.assertNotEqual(missing_local.user.id, preserved.user.id)

    async def test_subject_identity_wins_over_changed_google_email(self) -> None:
        identity = self._identity("subject")
        async with AsyncSessionFactory() as session:
            service = self._service(session, identity)
            first = await service.login_with_google("credential")
            service.google_verifier = StubGoogleVerifier(
                GoogleIdentity(
                    subject=identity.subject,
                    email=self._email("different"),
                    email_verified=True,
                )
            )
            second = await service.login_with_google("credential")
            self.assertEqual(second.user.id, first.user.id)
            self.assertEqual(second.user.email, identity.email)

    async def test_google_account_failure_rolls_back_new_user(self) -> None:
        identity = GoogleIdentity(
            subject="x" * 256,
            email=self._email("rollback"),
            email_verified=True,
        )
        async with AsyncSessionFactory() as session:
            service = self._service(session, identity)
            with self.assertRaises(DBAPIError):
                await service.login_with_google("credential")

            self.assertIsNone(
                await service.repository.get_user_by_email(identity.email)
            )

    def _identity(
        self,
        suffix: str,
        *,
        verified: bool = True,
        email_uppercase: bool = False,
    ) -> GoogleIdentity:
        email = self._email(suffix)
        if email_uppercase:
            email = email.upper()
        return GoogleIdentity(
            subject=f"google-sub-{self.test_id}-{suffix}",
            email=email,
            email_verified=verified,
            display_name="Google User",
            avatar_url="https://example.com/a.jpg",
        )

    def _email(self, suffix: str) -> str:
        return f"{self.email_prefix}-{suffix}@example.com"

    def _service(
        self,
        session,
        identity: GoogleIdentity,
    ) -> AuthService:
        return AuthService(
            session,
            clock=lambda: self.now,
            google_verifier=StubGoogleVerifier(identity),
        )


if __name__ == "__main__":
    unittest.main()
