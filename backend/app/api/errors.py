from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.security.google import (
    InvalidGoogleCredentialError,
    UnverifiedGoogleEmailError,
)
from app.services.auth import (
    EmailAlreadyRegisteredError,
    ExpiredRefreshTokenError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidEmailError,
    InvalidRefreshTokenError,
    PasswordPolicyError,
)


def register_auth_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        EmailAlreadyRegisteredError,
        _email_already_registered,
    )
    app.add_exception_handler(InvalidCredentialsError, _invalid_credentials)
    app.add_exception_handler(InactiveUserError, _inactive_user)
    app.add_exception_handler(InvalidEmailError, _invalid_email)
    app.add_exception_handler(PasswordPolicyError, _invalid_password)
    app.add_exception_handler(InvalidRefreshTokenError, _invalid_refresh)
    app.add_exception_handler(ExpiredRefreshTokenError, _invalid_refresh)
    app.add_exception_handler(
        InvalidGoogleCredentialError,
        _invalid_google_credential,
    )
    app.add_exception_handler(
        UnverifiedGoogleEmailError,
        _invalid_google_credential,
    )


async def _email_already_registered(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(status.HTTP_409_CONFLICT, "Email is already registered")


async def _invalid_credentials(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid email or password",
        authenticate=True,
    )


async def _inactive_user(request: Request, exc: Exception) -> JSONResponse:
    return _response(status.HTTP_403_FORBIDDEN, "User account is inactive")


async def _invalid_email(request: Request, exc: Exception) -> JSONResponse:
    return _response(
        422,
        "Invalid email address",
    )


async def _invalid_password(request: Request, exc: Exception) -> JSONResponse:
    return _response(
        422,
        "Password must be between 8 and 128 characters",
    )


async def _invalid_refresh(request: Request, exc: Exception) -> JSONResponse:
    return _response(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid refresh token",
        authenticate=True,
    )


async def _invalid_google_credential(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid Google credential",
        authenticate=True,
    )


def _response(
    status_code: int,
    detail: str,
    *,
    authenticate: bool = False,
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if authenticate else None
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers=headers,
    )
