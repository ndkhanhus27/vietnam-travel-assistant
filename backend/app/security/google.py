from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from google.auth.exceptions import GoogleAuthError as GoogleLibraryError
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from app.core.config import settings


class GoogleAuthError(Exception):
    """Base exception for Google identity verification failures."""


class InvalidGoogleCredentialError(GoogleAuthError):
    """Raised when a Google ID token cannot be trusted."""


class UnverifiedGoogleEmailError(GoogleAuthError):
    """Raised when Google has not verified the identity email."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    display_name: str | None = None
    avatar_url: str | None = None


class GoogleIdentityVerifier(Protocol):
    async def verify(self, credential: str) -> GoogleIdentity: ...


class GoogleAuthVerifier:
    def __init__(self, client_id: str | None = None) -> None:
        self.client_id = client_id or settings.google_client_id

    async def verify(self, credential: str) -> GoogleIdentity:
        if not self.client_id or not credential:
            raise InvalidGoogleCredentialError("Invalid Google credential")

        try:
            claims = await asyncio.to_thread(
                id_token.verify_oauth2_token,
                credential,
                Request(),
                self.client_id,
            )
            return _identity_from_claims(claims)
        except UnverifiedGoogleEmailError:
            raise
        except (GoogleLibraryError, TypeError, ValueError) as exc:
            raise InvalidGoogleCredentialError(
                "Invalid Google credential"
            ) from exc


def _identity_from_claims(claims: dict[str, Any]) -> GoogleIdentity:
    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(subject, str) or not subject:
        raise InvalidGoogleCredentialError("Invalid Google credential")
    if not isinstance(email, str) or not email:
        raise InvalidGoogleCredentialError("Invalid Google credential")
    if claims.get("email_verified") is not True:
        raise UnverifiedGoogleEmailError("Google email is not verified")

    display_name = claims.get("name")
    avatar_url = claims.get("picture")
    return GoogleIdentity(
        subject=subject,
        email=email,
        email_verified=True,
        display_name=display_name if isinstance(display_name, str) else None,
        avatar_url=avatar_url if isinstance(avatar_url, str) else None,
    )
