from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User
from app.db.repositories.auth import AuthRepository
from app.security.password import (
    hash_password,
    needs_rehash,
    verify_password,
)
from app.security.tokens import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)


MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class AuthError(Exception):
    """Base exception for local authentication use cases."""


class InvalidEmailError(AuthError):
    """Raised when an email address is not syntactically valid."""


class EmailAlreadyRegisteredError(AuthError):
    """Raised when an email address is already registered."""


class InvalidCredentialsError(AuthError):
    """Raised for every invalid local email/password combination."""


class InactiveUserError(AuthError):
    """Raised when authentication is attempted for an inactive user."""


class InvalidRefreshTokenError(AuthError):
    """Raised when a refresh token is unknown, revoked, or malformed."""


class ExpiredRefreshTokenError(AuthError):
    """Raised when a refresh token has expired."""


class PasswordPolicyError(AuthError):
    """Raised when a password falls outside the supported length range."""


class UserNotFoundError(AuthError):
    """Raised when a requested user does not exist."""


@dataclass(frozen=True, slots=True)
class AuthResult:
    user: User
    access_token: str
    refresh_token: str
    access_token_expires_in: int


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.repository = AuthRepository(session)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def register(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> AuthResult:
        normalized_email = normalize_email(email)

        try:
            _validate_email(normalized_email)
            _validate_password(password)

            if await self.repository.get_user_by_email(normalized_email):
                raise EmailAlreadyRegisteredError(
                    "Email address is already registered"
                )

            now = self._now()
            user = await self.repository.create_user(
                email=normalized_email,
                display_name=display_name,
                is_verified=False,
            )
            await self.repository.create_local_account(
                user_id=user.id,
                password_hash=hash_password(password),
            )
            result = await self._create_session(user, now)
            await self.session.commit()
            return result
        except IntegrityError as exc:
            await self.session.rollback()
            raise EmailAlreadyRegisteredError(
                "Email address is already registered"
            ) from exc
        except Exception:
            await self.session.rollback()
            raise

    async def login(self, email: str, password: str) -> AuthResult:
        normalized_email = normalize_email(email)

        try:
            user = await self.repository.get_user_by_email(normalized_email)
            if user is None:
                raise InvalidCredentialsError("Invalid email or password")
            if not user.is_active:
                raise InactiveUserError("User account is inactive")

            account = await self.repository.get_local_account_for_user(
                user.id
            )
            if (
                account is None
                or account.password_hash is None
                or not verify_password(account.password_hash, password)
            ):
                raise InvalidCredentialsError("Invalid email or password")

            if needs_rehash(account.password_hash):
                account.password_hash = hash_password(password)

            result = await self._create_session(user, self._now())
            await self.session.commit()
            return result
        except Exception:
            await self.session.rollback()
            raise

    async def refresh(self, raw_refresh_token: str) -> AuthResult:
        try:
            token_hash = _hash_refresh_token_or_raise(raw_refresh_token)
            stored_token = await self.repository.get_refresh_token_by_hash(
                token_hash
            )
            if stored_token is None or stored_token.revoked_at is not None:
                raise InvalidRefreshTokenError("Invalid refresh token")

            now = self._now()
            if stored_token.expires_at <= now:
                raise ExpiredRefreshTokenError("Refresh token has expired")

            user = await self.repository.get_user_by_id(stored_token.user_id)
            if user is None:
                raise InvalidRefreshTokenError("Invalid refresh token")
            if not user.is_active:
                raise InactiveUserError("User account is inactive")

            new_raw_token = generate_refresh_token()
            await self.repository.rotate_refresh_token(
                stored_token,
                new_token_hash=hash_refresh_token(new_raw_token),
                new_expires_at=now
                + timedelta(days=settings.refresh_token_expire_days),
                now=now,
            )
            result = AuthResult(
                user=user,
                access_token=create_access_token(user.id, now=now),
                refresh_token=new_raw_token,
                access_token_expires_in=(
                    settings.access_token_expire_minutes * 60
                ),
            )
            await self.session.commit()
            return result
        except Exception:
            await self.session.rollback()
            raise

    async def logout(self, raw_refresh_token: str) -> None:
        try:
            if raw_refresh_token:
                stored_token = (
                    await self.repository.get_refresh_token_by_hash(
                        hash_refresh_token(raw_refresh_token)
                    )
                )
                now = self._now()
                if (
                    stored_token is not None
                    and stored_token.revoked_at is None
                    and stored_token.expires_at > now
                ):
                    await self.repository.revoke_refresh_token(
                        stored_token,
                        now,
                    )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def logout_all(self, user_id: uuid.UUID) -> int:
        try:
            revoked_count = (
                await self.repository.revoke_all_refresh_tokens_for_user(
                    user_id,
                    self._now(),
                )
            )
            await self.session.commit()
            return revoked_count
        except Exception:
            await self.session.rollback()
            raise

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.repository.get_user_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found")
        if not user.is_active:
            raise InactiveUserError("User account is inactive")
        return user

    async def _create_session(
        self,
        user: User,
        now: datetime,
    ) -> AuthResult:
        raw_refresh_token = generate_refresh_token()
        await self.repository.create_refresh_token(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=now
            + timedelta(days=settings.refresh_token_expire_days),
        )
        return AuthResult(
            user=user,
            access_token=create_access_token(user.id, now=now),
            refresh_token=raw_refresh_token,
            access_token_expires_in=(
                settings.access_token_expire_minutes * 60
            ),
        )

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("AuthService clock must return an aware datetime")
        return now.astimezone(timezone.utc)


def _validate_email(email: str) -> None:
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        raise InvalidEmailError("Invalid email address") from exc


def _validate_password(password: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be between {MIN_PASSWORD_LENGTH} and "
            f"{MAX_PASSWORD_LENGTH} characters"
        )


def _hash_refresh_token_or_raise(raw_refresh_token: str) -> str:
    try:
        return hash_refresh_token(raw_refresh_token)
    except (TypeError, ValueError) as exc:
        raise InvalidRefreshTokenError("Invalid refresh token") from exc
