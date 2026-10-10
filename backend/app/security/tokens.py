from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from jwt.exceptions import PyJWTError

from app.core.config import settings


class TokenError(Exception):
    """Base exception for token validation failures."""


class InvalidTokenError(TokenError):
    """Raised when a token is malformed or fails validation."""


class ExpiredTokenError(TokenError):
    """Raised when a token is valid but expired."""


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    sub: uuid.UUID
    type: Literal["access"]
    iat: datetime
    exp: datetime
    jti: str
    auth_version: int = 0

    @property
    def user_id(self) -> uuid.UUID:
        return self.sub


def create_access_token(
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
    auth_version: int = 0,
) -> str:
    issued_at = _as_utc(now or datetime.now(timezone.utc))
    expires_at = issued_at + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": issued_at,
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
        "auth_version": auth_version,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(
    token: str,
    *,
    now: datetime | None = None,
) -> AccessTokenClaims:
    current_time = _as_utc(now or datetime.now(timezone.utc))
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={
                "require": ["sub", "type", "iat", "exp", "jti"],
                "verify_exp": False,
                "verify_iat": False,
            },
        )
        claims = _parse_access_claims(payload)
    except PyJWTError as exc:
        raise InvalidTokenError("Invalid access token") from exc
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidTokenError("Invalid access token claims") from exc

    if claims.exp <= current_time:
        raise ExpiredTokenError("Access token has expired")
    if claims.iat > current_time:
        raise InvalidTokenError("Access token was issued in the future")
    return claims


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    if not token:
        raise ValueError("Refresh token must not be empty")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_access_claims(payload: dict[str, Any]) -> AccessTokenClaims:
    if payload.get("type") != "access":
        raise ValueError("Unexpected token type")

    subject = payload.get("sub")
    jti = payload.get("jti")
    if not isinstance(subject, str) or not isinstance(jti, str) or not jti:
        raise ValueError("Invalid subject or token identifier")

    return AccessTokenClaims(
        sub=uuid.UUID(subject),
        type="access",
        iat=_timestamp_to_datetime(payload.get("iat")),
        exp=_timestamp_to_datetime(payload.get("exp")),
        jti=jti,
        auth_version=int(payload.get("auth_version", 0)),
    )


def _timestamp_to_datetime(value: Any) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("JWT timestamp must be numeric")
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Token timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
