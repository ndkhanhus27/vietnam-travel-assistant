from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_auth_service, get_current_user
from app.api.schemas import UpdateUserRequest, UserResponse
from app.db.models import User
from app.services.auth import AuthService


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UpdateUserRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    return await service.update_display_name(
        current_user,
        payload.display_name,
    )
