from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import (
    enforce_auth_rate_limit,
    get_auth_service,
    get_current_user,
)
from app.api.schemas import (
    AuthResponse,
    CreateLocalPasswordRequest,
    GoogleLoginRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
)
from app.db.models import User
from app.services.auth import AuthService


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    responses={429: {"description": "Rate limit exceeded"}},
)
async def register(
    payload: RegisterRequest,
    _: Annotated[None, Depends(enforce_auth_rate_limit)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    result = await service.register(
        payload.email,
        payload.password,
        payload.display_name,
    )
    return AuthResponse.from_result(result)


@router.post(
    "/login",
    response_model=AuthResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
async def login(
    payload: LoginRequest,
    _: Annotated[None, Depends(enforce_auth_rate_limit)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    return AuthResponse.from_result(
        await service.login(payload.email, payload.password)
    )


@router.post(
    "/google",
    response_model=AuthResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
async def google_login(
    payload: GoogleLoginRequest,
    _: Annotated[None, Depends(enforce_auth_rate_limit)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    return AuthResponse.from_result(
        await service.login_with_google(payload.credential)
    )


@router.post(
    "/local-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def create_local_password(
    payload: CreateLocalPasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    _: Annotated[None, Depends(enforce_auth_rate_limit)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    await service.create_local_password(current_user, payload.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/refresh",
    response_model=AuthResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
async def refresh(
    payload: RefreshRequest,
    _: Annotated[None, Depends(enforce_auth_rate_limit)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    return AuthResponse.from_result(
        await service.refresh(payload.refresh_token)
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def logout(
    payload: LogoutRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    await service.logout(payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def logout_all(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    await service.logout_all(current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
