from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.auth import AuthResult
from app.services.chat import ChatResult, MAX_CHAT_MESSAGE_LENGTH


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleLoginRequest(BaseModel):
    credential: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    avatar_url: str | None
    is_verified: bool


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserResponse

    @classmethod
    def from_result(cls, result: AuthResult) -> AuthResponse:
        return cls(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_in=result.access_token_expires_in,
            user=UserResponse.model_validate(result.user),
        )


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message must not be empty")
        if len(normalized) > MAX_CHAT_MESSAGE_LENGTH:
            raise ValueError(
                f"Message must not exceed {MAX_CHAT_MESSAGE_LENGTH} characters"
            )
        return normalized


class CitationResponse(BaseModel):
    citation_id: str
    evidence_id: str | None = None
    task_id: str | None = None
    title: str
    url: str | None = None
    source_type: str
    tool: str | None = None
    provider: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant", "system"]
    content: str
    sequence_no: int
    intent: str | None
    citations: list[CitationResponse] | None
    warnings: list[str] | None
    created_at: datetime


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: Literal["running", "success", "degraded", "failed"]
    intent: str | None
    retrieval_mode: str | None
    latency_ms: int | None
    retry_count: int
    tools_used: list[str] | None
    created_at: datetime
    completed_at: datetime | None


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    user_message: MessageResponse
    assistant_message: MessageResponse
    agent_run: AgentRunResponse

    @classmethod
    def from_result(cls, result: ChatResult) -> ChatResponse:
        return cls(
            conversation_id=result.user_message.conversation_id,
            user_message=MessageResponse.model_validate(result.user_message),
            assistant_message=MessageResponse.model_validate(
                result.assistant_message
            ),
            agent_run=AgentRunResponse.model_validate(result.agent_run),
        )


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return _normalize_conversation_title(value)


class UpdateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    is_archived: bool = False

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return _normalize_conversation_title(value)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None
    is_archived: bool


def _normalize_conversation_title(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 255:
        raise ValueError("Conversation title must not exceed 255 characters")
    return normalized
