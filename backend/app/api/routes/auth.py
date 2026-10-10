from __future__ import annotations

from typing import Annotated
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from app.db.session import AsyncSessionFactory
from app.services.mail import RecoveryMailer

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
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.db.models import User
from app.services.auth import AuthService


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/methods")
async def authentication_methods(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, bool]:
    accounts = await service.repository.list_auth_accounts_for_user(current_user.id)
    return {
        "has_password": any(account.provider == "local" for account in accounts),
        "google_linked": any(account.provider == "google" for account in accounts),
    }


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
    responses={
        409: {"description": "Email belongs to an unlinked account"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def google_login(
    payload: GoogleLoginRequest,
    _: Annotated[None, Depends(enforce_auth_rate_limit)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    return AuthResponse.from_result(
        await service.login_with_google(payload.credential, payload.password)
    )


@router.post("/forgot-password", dependencies=[Depends(enforce_auth_rate_limit)])
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, str]:
    background_tasks.add_task(_send_recovery, str(payload.email), service.mailer)
    return {"message": (
        "Nếu email có tài khoản mật khẩu đang hoạt động, bạn sẽ nhận được liên kết đặt lại mật khẩu. "
        "Nếu đã đăng ký bằng Google, hãy tiếp tục đăng nhập bằng Google."
    )}


async def _send_recovery(email: str, mailer: RecoveryMailer) -> None:
    try:
        async with AsyncSessionFactory() as session:
            await AuthService(session, mailer=mailer).request_password_reset(email)
    except Exception:
        logging.getLogger(__name__).error("Password recovery background task failed")


@router.post(
    "/reset-password", status_code=204, response_class=Response,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def reset_password(
    payload: ResetPasswordRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    await service.reset_password(payload.token, payload.password)
    return Response(status_code=204)


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
