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
    GoogleAccountLinkRequiredError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidEmailError,
    InvalidRefreshTokenError,
    LocalPasswordAlreadyConfiguredError,
    PasswordPolicyError,
    InvalidPasswordResetError,
    UnsupportedEmailDomainError,
)
from app.services.chat import (
    ChatWorkflowError,
    ConversationNotFoundError,
    InvalidChatMessageError,
)


def register_auth_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(UnsupportedEmailDomainError, _unsupported_email_domain)
    app.add_exception_handler(InvalidPasswordResetError, _invalid_password_reset)
    app.add_exception_handler(
        EmailAlreadyRegisteredError,
        _email_already_registered,
    )
    app.add_exception_handler(InvalidCredentialsError, _invalid_credentials)
    app.add_exception_handler(InactiveUserError, _inactive_user)
    app.add_exception_handler(InvalidEmailError, _invalid_email)
    app.add_exception_handler(PasswordPolicyError, _invalid_password)
    app.add_exception_handler(
        LocalPasswordAlreadyConfiguredError,
        _local_password_already_configured,
    )
    app.add_exception_handler(
        GoogleAccountLinkRequiredError,
        _google_account_link_required,
    )
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


def register_chat_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        ConversationNotFoundError,
        _conversation_not_found,
    )
    app.add_exception_handler(
        InvalidChatMessageError,
        _invalid_chat_message,
    )
    app.add_exception_handler(ChatWorkflowError, _chat_workflow_failed)


async def _email_already_registered(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(status.HTTP_409_CONFLICT, "Email này đã được đăng ký")


async def _invalid_credentials(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(
        status.HTTP_401_UNAUTHORIZED,
        "Email hoặc mật khẩu không đúng",
        authenticate=True,
    )


async def _inactive_user(request: Request, exc: Exception) -> JSONResponse:
    return _response(status.HTTP_403_FORBIDDEN, "Tài khoản đã bị vô hiệu hoá")


async def _invalid_email(request: Request, exc: Exception) -> JSONResponse:
    return _response(
        422,
        "Địa chỉ email không hợp lệ",
    )


async def _invalid_password(request: Request, exc: Exception) -> JSONResponse:
    return _response(
        422,
        "Mật khẩu phải có từ 8 đến 128 ký tự",
    )


async def _local_password_already_configured(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(
        status.HTTP_409_CONFLICT,
        "Tài khoản đã có mật khẩu đăng nhập",
    )


async def _google_account_link_required(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(
        status.HTTP_409_CONFLICT,
        "Email này đã có tài khoản. Xác nhận mật khẩu để liên kết Google, hoặc chọn Quên mật khẩu.",
    )


async def _invalid_refresh(request: Request, exc: Exception) -> JSONResponse:
    return _response(
        status.HTTP_401_UNAUTHORIZED,
        "Phiên đăng nhập không hợp lệ hoặc đã hết hạn",
        authenticate=True,
    )


async def _invalid_password_reset(request: Request, exc: Exception) -> JSONResponse:
    return _response(400, "Liên kết đặt lại mật khẩu không hợp lệ, đã hết hạn hoặc đã dùng. Hãy yêu cầu liên kết mới.")


async def _unsupported_email_domain(request: Request, exc: Exception) -> JSONResponse:
    return _response(422, "Chỉ hỗ trợ địa chỉ @gmail.com. Vui lòng sử dụng tài khoản Gmail.")


async def _invalid_google_credential(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(
        status.HTTP_401_UNAUTHORIZED,
        "Thông tin đăng nhập Google không hợp lệ",
        authenticate=True,
    )


async def _conversation_not_found(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(status.HTTP_404_NOT_FOUND, "Không tìm thấy cuộc trò chuyện")


async def _invalid_chat_message(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Nội dung tin nhắn không hợp lệ",
    )


async def _chat_workflow_failed(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _response(
        status.HTTP_502_BAD_GATEWAY,
        "Trợ lý chưa thể hoàn tất câu trả lời.",
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
