from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import User
from app.db.repositories.conversations import ConversationRepository
from app.db.session import AsyncSessionFactory
from app.security.google import GoogleAuthVerifier, GoogleIdentityVerifier
from app.security.tokens import TokenError, decode_access_token
from app.services.auth import AuthService, InactiveUserError, UserNotFoundError
from app.services.chat import ChatService, WorkflowRunner


bearer_scheme = HTTPBearer(auto_error=False)


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
            detail="User account is inactive",
        ) from exc
    except (TokenError, UserNotFoundError) as exc:
        raise _unauthorized() from exc


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
