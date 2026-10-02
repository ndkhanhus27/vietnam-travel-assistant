from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User
from app.db.repositories.conversations import ConversationRepository
from app.db.session import AsyncSessionFactory
from app.infra.redis import RedisRateLimiter
from app.security.google import GoogleAuthVerifier, GoogleIdentityVerifier
from app.security.tokens import TokenError, decode_access_token
from app.services.auth import AuthService, InactiveUserError, UserNotFoundError
from app.services.chat import ChatService, WorkflowRunner


bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionFactory() as session:
        yield session


def get_google_verifier() -> GoogleIdentityVerifier:
    return GoogleAuthVerifier()


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    google_verifier: Annotated[
        GoogleIdentityVerifier,
        Depends(get_google_verifier),
    ],
) -> AuthService:
    return AuthService(session, google_verifier=google_verifier)


def get_travel_workflow(request: Request) -> WorkflowRunner:
    workflow = getattr(request.app.state, "travel_workflow", None)
    if workflow is None:
        raise RuntimeError("Travel workflow is not initialized")
    return workflow


def get_redis(request: Request):
    return getattr(request.app.state, "redis", None)


def get_rate_limiter(
    redis_client: Annotated[object | None, Depends(get_redis)],
) -> RedisRateLimiter | None:
    if redis_client is None:
        return None
    return RedisRateLimiter(redis_client)


async def enforce_auth_rate_limit(
    request: Request,
    limiter: Annotated[
        RedisRateLimiter | None,
        Depends(get_rate_limiter),
    ],
) -> None:
    identity = request.client.host if request.client is not None else "unknown"
    endpoint = request.url.path.rstrip("/").rsplit("/", 1)[-1]
    await _enforce_rate_limit(
        limiter=limiter,
        scope=f"auth-{endpoint}",
        identity=identity,
        limit=settings.rate_limit_auth_requests,
        window_seconds=settings.rate_limit_auth_window_seconds,
    )


def get_chat_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    workflow: Annotated[WorkflowRunner, Depends(get_travel_workflow)],
) -> ChatService:
    return ChatService(session, workflow)


def get_conversation_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationRepository:
    return ConversationRepository(session)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        claims = decode_access_token(credentials.credentials)
        return await auth_service.get_user(claims.user_id)
    except InactiveUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị vô hiệu hoá",
        ) from exc
    except (TokenError, UserNotFoundError) as exc:
        raise _unauthorized() from exc


async def require_admin_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn cần quyền quản trị viên để truy cập",
        )
    return current_user


async def enforce_chat_rate_limit(
    current_user: Annotated[User, Depends(get_current_user)],
    limiter: Annotated[
        RedisRateLimiter | None,
        Depends(get_rate_limiter),
    ],
) -> None:
    await _enforce_rate_limit(
        limiter=limiter,
        scope="chat",
        identity=current_user.id,
        limit=settings.rate_limit_chat_requests,
        window_seconds=settings.rate_limit_chat_window_seconds,
    )


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Thiếu hoặc sai thông tin xác thực",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _enforce_rate_limit(
    *,
    limiter: RedisRateLimiter | None,
    scope: str,
    identity: object,
    limit: int,
    window_seconds: int,
) -> None:
    if not settings.rate_limit_enabled or limiter is None:
        return

    try:
        result = await limiter.check(
            scope=scope,
            identity=identity,
            limit=limit,
            window_seconds=window_seconds,
        )
    except (RedisError, OSError) as exc:
        logger.warning(
            "Redis rate limiter unavailable; request allowed: %s",
            type(exc).__name__,
        )
        return

    if result.allowed:
        return

    logger.warning("Rate limit exceeded for scope=%s", scope)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Bạn thao tác quá nhanh. Vui lòng thử lại sau.",
        headers={"Retry-After": str(result.retry_after)},
    )
