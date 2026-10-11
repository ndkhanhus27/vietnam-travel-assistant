from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    AdminAgentRunPage,
    AdminAgentRunResponse,
    AdminConversationDetailResponse,
    AdminConversationMessageResponse,
    AdminConversationPage,
    AdminConversationResponse,
    AdminKnowledgeResponse,
    AdminOverviewResponse,
    AdminUserPage,
    AdminUserResponse,
    AdminUserUpdateRequest,
)
from app.core.config import settings
from app.api.dependencies import get_db_session, require_admin_user
from app.db.models import User
from app.db.repositories.admin import AdminRepository


router = APIRouter(prefix="/admin", tags=["administration"])


@router.get("/overview", response_model=AdminOverviewResponse)
async def get_overview(
    _: Annotated[User, Depends(require_admin_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    return await AdminRepository(session).overview()


@router.get("/users", response_model=AdminUserPage)
async def list_users(
    _: Annotated[User, Depends(require_admin_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(max_length=200)] = None,
    role: Annotated[str | None, Query(pattern="^(admin|user)$")] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", pattern="^(active|blocked)$"),
    ] = None,
    provider: Annotated[str | None, Query(pattern="^(google|local)$")] = None,
) -> AdminUserPage:
    rows, total = await AdminRepository(session).list_users(
        limit=limit,
        offset=offset,
        query=q,
        role=role,
        status=status_filter,
        provider=provider,
    )
    return AdminUserPage(
        items=[
            AdminUserResponse(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                is_active=user.is_active,
                is_admin=user.is_admin,
                is_verified=user.is_verified,
                created_at=user.created_at,
                conversation_count=conversation_count,
                run_count=run_count,
                providers=providers,
                last_login_at=last_login_at,
            )
            for user, conversation_count, run_count, providers, last_login_at in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdateRequest,
    current_admin: Annotated[User, Depends(require_admin_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminUserResponse:
    if user_id == current_admin.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bạn không thể tự vô hiệu hoá tài khoản của mình",
        )
    repository = AdminRepository(session)
    user = await repository.get_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy người dùng",
        )
    await repository.set_user_active(user, payload.is_active)
    await session.commit()
    conversation_count, run_count = await repository.get_user_counts(
        user.id
    )
    providers, last_login_at = await repository.get_user_auth_summary(user.id)
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_admin=user.is_admin,
        is_verified=user.is_verified,
        created_at=user.created_at,
        conversation_count=conversation_count,
        run_count=run_count,
        providers=providers,
        last_login_at=last_login_at,
    )


@router.get("/agent-runs", response_model=AdminAgentRunPage)
async def list_agent_runs(
    _: Annotated[User, Depends(require_admin_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(max_length=200)] = None,
    intent: Annotated[str | None, Query(max_length=50)] = None,
    retrieval_mode: Annotated[str | None, Query(max_length=50)] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", pattern="^(running|success|degraded|failed)$"),
    ] = None,
) -> AdminAgentRunPage:
    rows, total = await AdminRepository(session).list_agent_runs(
        limit=limit,
        offset=offset,
        query=q,
        intent=intent,
        retrieval_mode=retrieval_mode,
        status=status_filter,
    )
    def citation_summary(
        citations: list[dict[str, object]] | None,
    ) -> tuple[int, int]:
        items = citations or []
        evidence_ids = {
            str(item["evidence_id"])
            for item in items
            if item.get("evidence_id")
        }
        return len(items), len(evidence_ids)

    return AdminAgentRunPage(
        items=[
            AdminAgentRunResponse(
                id=run.id,
                conversation_id=run.conversation_id,
                user_email=email,
                user_display_name=display_name,
                intent=run.intent,
                retrieval_mode=run.retrieval_mode,
                status=run.status,
                latency_ms=run.latency_ms,
                retry_count=run.retry_count,
                tools_used=run.tools_used,
                grounded=bool(citations),
                citation_count=citation_summary(citations)[0],
                evidence_count=citation_summary(citations)[1],
                error_code=run.error_code,
                created_at=run.created_at,
                completed_at=run.completed_at,
            )
            for run, email, display_name, citations in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def _conversation_response(row: tuple) -> AdminConversationResponse:
    (
        conversation,
        email,
        display_name,
        message_count,
        run_count,
        last_intent,
        last_mode,
    ) = row
    return AdminConversationResponse(
        id=conversation.id,
        title=conversation.title,
        user_id=conversation.user_id,
        user_email=email,
        user_display_name=display_name,
        message_count=message_count,
        run_count=run_count,
        last_intent=last_intent,
        last_retrieval_mode=last_mode,
        is_archived=conversation.is_archived,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at,
    )


@router.get("/conversations", response_model=AdminConversationPage)
async def list_conversations(
    _: Annotated[User, Depends(require_admin_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(max_length=200)] = None,
    user_id: uuid.UUID | None = None,
) -> AdminConversationPage:
    rows, total = await AdminRepository(session).list_conversations(
        limit=limit,
        offset=offset,
        query=q,
        user_id=user_id,
    )
    return AdminConversationPage(
        items=[_conversation_response(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=AdminConversationDetailResponse,
)
async def get_conversation(
    conversation_id: uuid.UUID,
    _: Annotated[User, Depends(require_admin_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminConversationDetailResponse:
    detail = await AdminRepository(session).get_conversation_detail(
        conversation_id
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    *summary, messages = detail
    base = _conversation_response(tuple(summary))
    return AdminConversationDetailResponse(
        **base.model_dump(),
        messages=[
            AdminConversationMessageResponse.model_validate(message)
            for message in messages
        ],
    )


def _read_qdrant_status() -> dict[str, object]:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=settings.qdrant_url, timeout=5)
    try:
        info = client.get_collection(settings.qdrant_collection)
        vectors = info.config.params.vectors
        if isinstance(vectors, dict):
            vectors = next(iter(vectors.values()), None)
        return {
            "qdrant_status": str(info.status).split(".")[-1].lower(),
            "points": info.points_count,
            "vector_size": getattr(vectors, "size", None),
            "distance": (
                str(getattr(vectors, "distance", "")).split(".")[-1]
                or None
            ),
        }
    finally:
        client.close()


@router.get("/knowledge", response_model=AdminKnowledgeResponse)
async def get_knowledge_status(
    _: Annotated[User, Depends(require_admin_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminKnowledgeResponse:
    from starlette.concurrency import run_in_threadpool

    result = await AdminRepository(session).knowledge_counts()
    try:
        qdrant = await run_in_threadpool(_read_qdrant_status)
    except Exception:
        qdrant = {
            "qdrant_status": "unavailable",
            "points": None,
            "vector_size": None,
            "distance": None,
        }
    return AdminKnowledgeResponse(
        **result,
        collection=settings.qdrant_collection,
        **qdrant,
    )
