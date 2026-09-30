from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import (
    get_conversation_repository,
    get_current_user,
)
from app.api.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    UpdateConversationRequest,
)
from app.db.models import Conversation, Message, User
from app.db.repositories.conversations import ConversationRepository
from app.services.chat import ConversationNotFoundError


router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: CreateConversationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        ConversationRepository,
        Depends(get_conversation_repository),
    ],
) -> Conversation:
    try:
        conversation = await repository.create_conversation(
            user_id=current_user.id,
            title=payload.title,
        )
        await repository.session.commit()
        await repository.session.refresh(conversation)
        return conversation
    except Exception:
        await repository.session.rollback()
        raise


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        ConversationRepository,
        Depends(get_conversation_repository),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_archived: bool = False,
) -> list[Conversation]:
    return await repository.list_conversations_for_user(
        current_user.id,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    responses={404: {"description": "Conversation not found"}},
)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        ConversationRepository,
        Depends(get_conversation_repository),
    ],
) -> Conversation:
    return await _get_owned_conversation(
        repository,
        conversation_id,
        current_user.id,
    )


@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    responses={404: {"description": "Conversation not found"}},
)
async def update_conversation(
    conversation_id: uuid.UUID,
    payload: UpdateConversationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        ConversationRepository,
        Depends(get_conversation_repository),
    ],
) -> Conversation:
    try:
        conversation = await _get_owned_conversation(
            repository,
            conversation_id,
            current_user.id,
        )
        supplied_fields = payload.model_fields_set
        if "title" in supplied_fields:
            await repository.update_conversation_title(
                conversation,
                payload.title,
            )
        if "is_archived" in supplied_fields:
            await repository.archive_conversation(
                conversation,
                payload.is_archived,
            )
        await repository.session.commit()
        await repository.session.refresh(conversation)
        return conversation
    except Exception:
        await repository.session.rollback()
        raise


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={404: {"description": "Conversation not found"}},
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        ConversationRepository,
        Depends(get_conversation_repository),
    ],
) -> Response:
    try:
        conversation = await _get_owned_conversation(
            repository,
            conversation_id,
            current_user.id,
        )
        await repository.delete_conversation(conversation)
        await repository.session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception:
        await repository.session.rollback()
        raise


@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageResponse],
    responses={404: {"description": "Conversation not found"}},
)
async def list_conversation_messages(
    conversation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        ConversationRepository,
        Depends(get_conversation_repository),
    ],
) -> list[Message]:
    await _get_owned_conversation(
        repository,
        conversation_id,
        current_user.id,
    )
    return await repository.list_messages(
        conversation_id,
        current_user.id,
    )


async def _get_owned_conversation(
    repository: ConversationRepository,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Conversation:
    conversation = await repository.get_conversation_by_id(
        conversation_id,
        user_id,
    )
    if conversation is None:
        raise ConversationNotFoundError("Conversation not found")
    return conversation
