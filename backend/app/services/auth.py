from __future__ import annotations

import uuid
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User, PasswordResetToken
from app.services.mail import RecoveryMailer, SmtpRecoveryMailer, MailDeliveryError
from app.db.repositories.auth import AuthRepository
from app.security.google import (
    GoogleAuthVerifier,
    GoogleIdentity,
    GoogleIdentityVerifier,
    InvalidGoogleCredentialError,
    UnverifiedGoogleEmailError,
)
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


class UnsupportedEmailDomainError(AuthError):
    """Only personal Gmail addresses may authenticate."""


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


class LocalPasswordAlreadyConfiguredError(AuthError):
    """Raised when create-password is used for an existing local account."""


class GoogleAccountLinkRequiredError(AuthError):
    """Raised when Google matches an existing account but is not linked."""


class UserNotFoundError(AuthError):
    """Raised when a requested user does not exist."""


class InvalidPasswordResetError(AuthError):
    """Recovery token is invalid, expired, or already used."""


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
        google_verifier: GoogleIdentityVerifier | None = None,
        mailer: RecoveryMailer | None = None,
    ) -> None:
        self.session = session
        self.repository = AuthRepository(session)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.google_verifier = google_verifier or GoogleAuthVerifier()
        self.mailer = mailer or SmtpRecoveryMailer()

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
        _validate_email(normalized_email)

        try:
            user = await self.repository.get_user_by_email(normalized_email, for_update=True)
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

    async def login_with_google(
        self, credential: str, password: str | None = None,
    ) -> AuthResult:
        identity = await self.google_verifier.verify(credential)
        if not identity.email_verified:
            raise UnverifiedGoogleEmailError("Google email is not verified")

        try:
            normalized_email = normalize_email(identity.email)
            try:
                _validate_email(normalized_email)
            except InvalidEmailError as exc:
                raise InvalidGoogleCredentialError(
                    "Invalid Google credential"
                ) from exc

            account = await self.repository.get_google_account(
                identity.subject
            )
            if account is not None:
                user = await self.repository.get_user_by_id(account.user_id, for_update=True)
                if user is None:
                    raise InvalidGoogleCredentialError(
                        "Invalid Google credential"
                    )
            else:
                user = await self.repository.get_user_by_email(
                    normalized_email, for_update=True
                )
                if user is not None:
                    if not user.is_active:
                        raise InactiveUserError("User account is inactive")
                    if password is None:
                        raise GoogleAccountLinkRequiredError("Confirm the existing account password to link Google")
                    local = await self.repository.get_local_account_for_user(user.id)
                    if (
                        local is None or not local.password_hash
                        or not verify_password(local.password_hash, password)
                    ):
                        raise InvalidCredentialsError("Invalid email or password")
                else:
                    user = await self.repository.create_user(
                        email=normalized_email,
                        display_name=identity.display_name,
                        avatar_url=identity.avatar_url,
                        is_verified=True,
                    )
                await self.repository.create_google_account(
                    user_id=user.id,
                    provider_user_id=identity.subject,
                )

            if not user.is_active:
                raise InactiveUserError("User account is inactive")

            await self._merge_google_profile(user, identity)
            result = await self._create_session(user, self._now())
            await self.session.commit()
            return result
        except IntegrityError as exc:
            await self.session.rollback()
            raise InvalidGoogleCredentialError(
                "Google account could not be linked"
            ) from exc
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

            user = await self.repository.get_user_by_id(
                stored_token.user_id, for_update=True,
            )
            if user is None:
                raise InvalidRefreshTokenError("Invalid refresh token")
            await self.session.refresh(stored_token)
            if stored_token.revoked_at is not None:
                raise InvalidRefreshTokenError("Invalid refresh token")
            if not user.is_active:
                raise InactiveUserError("User account is inactive")
            _validate_email(user.email)

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
                access_token=create_access_token(user.id, now=now, auth_version=user.auth_version),
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
        _validate_email(user.email)
        return user

    async def update_display_name(
        self,
        user: User,
        display_name: str | None,
    ) -> User:
        try:
            updated = await self.repository.set_user_display_name(
                user,
                display_name,
            )
            await self.session.commit()
            return updated
        except Exception:
            await self.session.rollback()
            raise

    async def create_local_password(
        self,
        user: User,
        password: str,
    ) -> None:
        """Add a local credential once to an authenticated Google-first user."""

        try:
            _validate_password(password)
            existing = await self.repository.get_local_account_for_user(
                user.id
            )
            if existing is not None:
                raise LocalPasswordAlreadyConfiguredError(
                    "Local password is already configured"
                )
            await self.repository.create_local_account(
                user_id=user.id,
                password_hash=hash_password(password),
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise LocalPasswordAlreadyConfiguredError(
                "Local password is already configured"
            ) from exc
        except Exception:
            await self.session.rollback()
            raise

    async def _create_session(
        self,
        user: User,
        now: datetime,
    ) -> AuthResult:
        _validate_email(user.email)
        raw_refresh_token = generate_refresh_token()
        await self.repository.create_refresh_token(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=now
            + timedelta(days=settings.refresh_token_expire_days),
        )
        return AuthResult(
            user=user,
            access_token=create_access_token(user.id, now=now, auth_version=user.auth_version),
            refresh_token=raw_refresh_token,
            access_token_expires_in=(
                settings.access_token_expire_minutes * 60
            ),
        )

    async def request_password_reset(self, email: str) -> None:
        email = normalize_email(email)
        _validate_email(email)
        try:
            # Serialize recovery requests per account and limit email bursts.
            user = await self.repository.get_user_by_email(email, for_update=True)
            if user is None or not user.is_active:
                await self.session.rollback()
                return
            local = await self.repository.get_local_account_for_user(user.id)
            if local is None:
                await self.session.rollback()
                return
            now = self._now()
            latest = (await self.session.execute(
                select(PasswordResetToken)
                .where(PasswordResetToken.user_id == user.id)
                .order_by(PasswordResetToken.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if latest and latest.created_at > now - timedelta(seconds=60):
                await self.session.rollback()
                return
            raw = generate_refresh_token()
            token = PasswordResetToken(
                user_id=user.id,
                token_hash=hash_refresh_token(raw),
                expires_at=now + timedelta(minutes=settings.password_reset_expire_minutes),
                created_at=now,
            )
            self.session.add(token)
            await self.session.flush()
            link = f"{settings.public_app_url}/reset-password#token={raw}"
            await self.mailer.send_reset(user.email, link)
            await self.session.commit()
        except MailDeliveryError:
            await self.session.rollback()
            logging.getLogger(__name__).error("Password recovery mail delivery failed")
        except Exception:
            await self.session.rollback()
            raise

    async def reset_password(self, raw_token: str, password: str) -> None:
        _validate_password(password)
        if not raw_token:
            raise InvalidPasswordResetError()
        try:
            # Lock the user first so concurrent token use and recovery requests serialize.
            token_hash = hash_refresh_token(raw_token)
            user_id = (await self.session.execute(
                select(PasswordResetToken.user_id)
                .where(PasswordResetToken.token_hash == token_hash)
            )).scalar_one_or_none()
            if user_id is None:
                raise InvalidPasswordResetError()
            user = await self.repository.get_user_by_id(user_id, for_update=True)
            if user is None:
                raise InvalidPasswordResetError()
            token = (await self.session.execute(
                select(PasswordResetToken)
                .where(PasswordResetToken.token_hash == token_hash)
                .with_for_update()
            )).scalar_one_or_none()
            now = self._now()
            if token is None or not user.is_active or token.used_at is not None or token.expires_at <= now:
                raise InvalidPasswordResetError()
            local = await self.repository.get_local_account_for_user(user.id)
            if local is None:
                raise InvalidPasswordResetError()
            _validate_email(user.email)
            local.password_hash = hash_password(password)
            user.auth_version += 1
            user.is_verified = True
            await self.session.execute(
                update(PasswordResetToken)
                .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
                .values(used_at=now)
            )
            await self.repository.revoke_all_refresh_tokens_for_user(user.id, now)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def _merge_google_profile(
        self,
        user: User,
        identity: GoogleIdentity,
    ) -> None:
        if not user.is_verified:
            await self.repository.set_user_verified(user, True)
        if user.display_name is None or user.avatar_url is None:
            await self.repository.update_user_profile(
                user,
                display_name=(
                    identity.display_name
                    if user.display_name is None
                    else None
                ),
                avatar_url=(
                    identity.avatar_url
                    if user.avatar_url is None
                    else None
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
    if normalize_email(email).rsplit("@", 1)[-1] != "gmail.com":
        raise UnsupportedEmailDomainError("Only @gmail.com addresses are supported")


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
