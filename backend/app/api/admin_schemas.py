from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdminOverviewResponse(BaseModel):
    total_users: int
    active_users: int
    total_conversations: int
    total_runs: int
    successful_runs: int
    degraded_runs: int
    failed_runs: int
    requests_today: int
    average_latency_ms: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    tool_usage: dict[str, int]


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    is_active: bool
    is_admin: bool
    is_verified: bool
    created_at: datetime
    conversation_count: int
    run_count: int
    providers: list[str]
    last_login_at: datetime | None


class AdminUserPage(BaseModel):
    items: list[AdminUserResponse]
    total: int
    limit: int
    offset: int


class AdminUserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool


class AdminAgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    user_email: str
    user_display_name: str | None
    intent: str | None
    retrieval_mode: str | None
    status: str
    latency_ms: int | None
    retry_count: int
    tools_used: list[str] | None
    grounded: bool
    evidence_count: int
    citation_count: int
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class AdminAgentRunPage(BaseModel):
    items: list[AdminAgentRunResponse]
    total: int
    limit: int
    offset: int


class AdminConversationResponse(BaseModel):
    id: uuid.UUID
    title: str | None
    user_id: uuid.UUID
    user_email: str
    user_display_name: str | None
    message_count: int
    run_count: int
    last_intent: str | None
    last_retrieval_mode: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None


class AdminConversationPage(BaseModel):
    items: list[AdminConversationResponse]
    total: int
    limit: int
    offset: int


class AdminConversationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    sequence_no: int
    intent: str | None
    citations: list[dict[str, object]] | None
    warnings: list[str] | None
    created_at: datetime


class AdminConversationDetailResponse(AdminConversationResponse):
    messages: list[AdminConversationMessageResponse]


class AdminKnowledgeResponse(BaseModel):
    documents: int
    active_documents: int
    entity_candidates: int
    last_import_at: datetime | None
    collection: str
    qdrant_status: str
    points: int | None
    vector_size: int | None
    distance: str | None
