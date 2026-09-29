from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, Conversation, Message


class ConversationRepository:
    """Async persistence operations for conversations and agent runs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_conversation(
        self,
        *,
        user_id: uuid.UUID,
        title: str | None = None,
    ) -> Conversation:
        conversation = Conversation(user_id=user_id, title=title)
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get_conversation_by_id(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Conversation | None:
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_conversations_for_user(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[Conversation]:
        statement = select(Conversation).where(
            Conversation.user_id == user_id
        )
        if not include_archived:
            statement = statement.where(Conversation.is_archived.is_(False))

        statement = statement.order_by(
            Conversation.last_message_at.desc().nulls_last(),
            Conversation.updated_at.desc(),
            Conversation.created_at.desc(),
            Conversation.id.desc(),
        ).limit(limit).offset(offset)

        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def update_conversation_title(
        self,
        conversation: Conversation,
        title: str | None,
    ) -> Conversation:
        conversation.title = title
        await self.session.flush()
        return conversation

    async def archive_conversation(
        self,
        conversation: Conversation,
        archived: bool = True,
    ) -> Conversation:
        conversation.is_archived = archived
        await self.session.flush()
        return conversation

    async def delete_conversation(self, conversation: Conversation) -> None:
        await self.session.delete(conversation)
        await self.session.flush()

    async def add_message(
        self,
        *,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        intent: str | None = None,
        citations: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
    ) -> Message:
        conversation_result = await self.session.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .with_for_update()
        )
        conversation = conversation_result.scalar_one_or_none()
        if conversation is None:
            raise LookupError("Conversation not found")

        sequence_result = await self.session.execute(
            select(func.coalesce(func.max(Message.sequence_no), 0)).where(
                Message.conversation_id == conversation_id
            )
        )
        sequence_no = int(sequence_result.scalar_one()) + 1
        activity_at = datetime.now(timezone.utc)

        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sequence_no=sequence_no,
            intent=intent,
            citations=citations,
            warnings=warnings,
        )
        conversation.last_message_at = activity_at
        conversation.updated_at = activity_at
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_messages(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        limit: int | None = None,
    ) -> list[Message]:
        statement = (
            select(Message)
            .join(
                Conversation,
                Conversation.id == Message.conversation_id,
            )
            .where(
                Message.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .order_by(Message.sequence_no.asc())
        )
        if limit is not None:
            statement = statement.limit(limit)

        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_recent_messages(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int,
    ) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .join(
                Conversation,
                Conversation.id == Message.conversation_id,
            )
            .where(
                Message.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .order_by(Message.sequence_no.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def create_agent_run(
        self,
        *,
        conversation_id: uuid.UUID,
        user_message_id: uuid.UUID | None = None,
        intent: str | None = None,
        retrieval_mode: str | None = None,
        model_name: str | None = None,
    ) -> AgentRun:
        agent_run = AgentRun(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            intent=intent,
            retrieval_mode=retrieval_mode,
            model_name=model_name,
            status="running",
        )
        self.session.add(agent_run)
        await self.session.flush()
        return agent_run

    async def complete_agent_run(
        self,
        agent_run: AgentRun,
        *,
        status: str,
        assistant_message_id: uuid.UUID | None = None,
        latency_ms: int | None = None,
        retry_count: int = 0,
        tools_used: list[str] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> AgentRun:
        agent_run.status = status
        agent_run.assistant_message_id = assistant_message_id
        agent_run.latency_ms = latency_ms
        agent_run.retry_count = retry_count
        agent_run.tools_used = tools_used
        agent_run.error_code = error_code
        agent_run.error_message = error_message
        agent_run.completed_at = completed_at or datetime.now(timezone.utc)
        await self.session.flush()
        return agent_run

    async def get_agent_run_by_id(
        self,
        run_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
    ) -> AgentRun | None:
        statement = select(AgentRun).where(AgentRun.id == run_id)
        if conversation_id is not None:
            statement = statement.where(
                AgentRun.conversation_id == conversation_id
            )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_agent_runs_for_conversation(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[AgentRun]:
        result = await self.session.execute(
            select(AgentRun)
            .join(
                Conversation,
                Conversation.id == AgentRun.conversation_id,
            )
            .where(
                AgentRun.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
