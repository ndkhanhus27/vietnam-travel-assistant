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
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class AdminAgentRunPage(BaseModel):
    items: list[AdminAgentRunResponse]
    total: int
    limit: int
    offset: int
