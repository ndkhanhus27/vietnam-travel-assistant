from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    AdminAgentRunPage,
    AdminAgentRunResponse,
    AdminOverviewResponse,
    AdminUserPage,
    AdminUserResponse,
    AdminUserUpdateRequest,
)
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
) -> AdminUserPage:
    rows, total = await AdminRepository(session).list_users(
        limit=limit,
        offset=offset,
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
            )
            for user, conversation_count, run_count in rows
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
    )


@router.get("/agent-runs", response_model=AdminAgentRunPage)
async def list_agent_runs(
    _: Annotated[User, Depends(require_admin_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminAgentRunPage:
    rows, total = await AdminRepository(session).list_agent_runs(
        limit=limit,
        offset=offset,
    )
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
                error_code=run.error_code,
                created_at=run.created_at,
                completed_at=run.completed_at,
            )
            for run, email, display_name in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
