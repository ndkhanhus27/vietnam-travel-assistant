from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    enforce_chat_rate_limit,
    get_chat_service,
    get_current_user,
)
from app.api.schemas import ChatResponse, SendMessageRequest
from app.api.sse import encode_sse
from app.db.models import User
from app.services.chat import ChatResult, ChatService


router = APIRouter(prefix="/conversations", tags=["chat"])


@router.post(
    "/{conversation_id}/messages",
    response_model=ChatResponse,
    responses={
        401: {"description": "Invalid or missing access token"},
        404: {"description": "Conversation not found"},
        429: {"description": "Rate limit exceeded"},
        422: {"description": "Invalid message content"},
        502: {"description": "Assistant workflow failed"},
    },
)
async def send_message(
    conversation_id: uuid.UUID,
    payload: SendMessageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    _: Annotated[None, Depends(enforce_chat_rate_limit)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    result = await service.send_message(
        user_id=current_user.id,
        conversation_id=conversation_id,
        content=payload.content,
    )
    return ChatResponse.from_result(result)


@router.post(
    "/{conversation_id}/messages/stream",
    responses={
        200: {
            "description": "SSE chat execution stream",
            "content": {"text/event-stream": {}},
        },
        401: {"description": "Invalid or missing access token"},
        404: {"description": "Conversation not found"},
        429: {"description": "Rate limit exceeded"},
        422: {"description": "Invalid message content"},
    },
)
async def stream_message(
    conversation_id: uuid.UUID,
    payload: SendMessageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    _: Annotated[None, Depends(enforce_chat_rate_limit)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    events = await service.stream_message(
        user_id=current_user.id,
        conversation_id=conversation_id,
        content=payload.content,
    )

    async def event_generator():
        async for item in events:
            data = item.data
            if isinstance(data, ChatResult):
                data = ChatResponse.from_result(data).model_dump(mode="json")
            yield encode_sse(item.event, data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
