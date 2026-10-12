from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import (
    AgentRun,
    AuthAccount,
    Conversation,
    Document,
    EntityCandidate,
    Message,
    RefreshToken,
    User,
)


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(self) -> dict[str, object]:
        today = datetime.now(timezone.utc).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        count_queries = {
            "total_users": select(func.count(User.id)),
            "active_users": select(func.count(User.id)).where(
                User.is_active.is_(True)
            ),
            "total_conversations": select(func.count(Conversation.id)),
            "total_runs": select(func.count(AgentRun.id)),
            "successful_runs": select(func.count(AgentRun.id)).where(
                AgentRun.status == "success"
            ),
            "degraded_runs": select(func.count(AgentRun.id)).where(
                AgentRun.status == "degraded"
            ),
            "failed_runs": select(func.count(AgentRun.id)).where(
                AgentRun.status == "failed"
            ),
            "requests_today": select(func.count(AgentRun.id)).where(
                AgentRun.created_at >= today
            ),
        }
        result: dict[str, object] = {}
        for key, statement in count_queries.items():
            result[key] = int(
                (await self.session.execute(statement)).scalar_one()
            )

        latency_result = await self.session.execute(
            select(
                func.avg(AgentRun.latency_ms),
                func.percentile_cont(0.5).within_group(
                    AgentRun.latency_ms
                ),
                func.percentile_cont(0.95).within_group(
                    AgentRun.latency_ms
                ),
            ).where(AgentRun.latency_ms.is_not(None))
        )
        average, p50, p95 = latency_result.one()
        result.update(
            average_latency_ms=(round(float(average), 1) if average else None),
            p50_latency_ms=(round(float(p50), 1) if p50 else None),
            p95_latency_ms=(round(float(p95), 1) if p95 else None),
        )

        tools_result = await self.session.execute(
            select(AgentRun.tools_used).where(AgentRun.tools_used.is_not(None))
        )
        tool_counts: Counter[str] = Counter()
        for tools in tools_result.scalars():
            tool_counts.update(str(tool) for tool in (tools or []))
        result["tool_usage"] = dict(tool_counts.most_common())
        return result

    async def list_users(
        self,
        *,
        limit: int,
        offset: int,
        query: str | None = None,
        role: str | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> tuple[list[tuple[User, int, int, list[str], datetime | None]], int]:
        conversation_count = (
            select(func.count(Conversation.id))
            .where(Conversation.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )
        run_count = (
            select(func.count(AgentRun.id))
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .where(Conversation.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )
        providers = (
            select(func.array_agg(AuthAccount.provider))
            .where(AuthAccount.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )
        last_login = (
            select(func.max(func.coalesce(RefreshToken.last_used_at, RefreshToken.created_at)))
            .where(RefreshToken.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )
        filters = []
        if query:
            pattern = f"%{query.strip()}%"
            filters.append(or_(User.email.ilike(pattern), User.display_name.ilike(pattern)))
        if role == "admin":
            filters.append(User.is_admin.is_(True))
        elif role == "user":
            filters.append(User.is_admin.is_(False))
        if status == "active":
            filters.append(User.is_active.is_(True))
        elif status == "blocked":
            filters.append(User.is_active.is_(False))
        if provider:
            filters.append(
                select(AuthAccount.id)
                .where(
                    AuthAccount.user_id == User.id,
                    AuthAccount.provider == provider,
                )
                .exists()
            )
        rows = await self.session.execute(
            select(
                User,
                conversation_count.label("conversation_count"),
                run_count.label("run_count"),
                providers.label("providers"),
                last_login.label("last_login_at"),
            )
            .where(*filters)
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = int(
            (await self.session.execute(select(func.count(User.id)).where(*filters)))
            .scalar_one()
        )
        return [
            (user, int(conversations), int(runs), list(user_providers or []), login_at)
            for user, conversations, runs, user_providers, login_at in rows.all()
        ], total

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def set_user_active(self, user: User, active: bool) -> User:
        user.is_active = active
        await self.session.flush()
        return user

    async def get_user_counts(self, user_id: uuid.UUID) -> tuple[int, int]:
        conversation_count = int(
            (
                await self.session.execute(
                    select(func.count(Conversation.id)).where(
                        Conversation.user_id == user_id
                    )
                )
            ).scalar_one()
        )
        run_count = int(
            (
                await self.session.execute(
                    select(func.count(AgentRun.id))
                    .join(
                        Conversation,
                        Conversation.id == AgentRun.conversation_id,
                    )
                    .where(Conversation.user_id == user_id)
                )
            ).scalar_one()
        )
        return conversation_count, run_count

    async def get_user_auth_summary(
        self,
        user_id: uuid.UUID,
    ) -> tuple[list[str], datetime | None]:
        providers = list((await self.session.execute(
            select(AuthAccount.provider)
            .where(AuthAccount.user_id == user_id)
            .order_by(AuthAccount.provider)
        )).scalars())
        last_login = (await self.session.execute(
            select(func.max(func.coalesce(
                RefreshToken.last_used_at,
                RefreshToken.created_at,
            ))).where(RefreshToken.user_id == user_id)
        )).scalar_one()
        return providers, last_login

    async def list_agent_runs(
        self,
        *,
        limit: int,
        offset: int,
        query: str | None = None,
        intent: str | None = None,
        retrieval_mode: str | None = None,
        status: str | None = None,
    ) -> tuple[
        list[tuple[AgentRun, str, str | None, list[dict] | None]],
        int,
    ]:
        assistant_message = aliased(Message)
        filters = []
        if query:
            pattern = f"%{query.strip()}%"
            filters.append(or_(
                User.email.ilike(pattern),
                User.display_name.ilike(pattern),
                cast(AgentRun.id, String).ilike(pattern),
                cast(AgentRun.conversation_id, String).ilike(pattern),
            ))
        if intent:
            filters.append(AgentRun.intent == intent)
        if retrieval_mode:
            filters.append(AgentRun.retrieval_mode == retrieval_mode)
        if status:
            filters.append(AgentRun.status == status)
        rows = await self.session.execute(
            select(
                AgentRun,
                User.email,
                User.display_name,
                assistant_message.citations,
            )
            .join(
                Conversation,
                Conversation.id == AgentRun.conversation_id,
            )
            .join(User, User.id == Conversation.user_id)
            .outerjoin(
                assistant_message,
                assistant_message.id == AgentRun.assistant_message_id,
            )
            .where(*filters)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = int(
            (
                await self.session.execute(
                    select(func.count(AgentRun.id))
                    .join(Conversation, Conversation.id == AgentRun.conversation_id)
                    .join(User, User.id == Conversation.user_id)
                    .where(*filters)
                )
            )
            .scalar_one()
        )
        return list(rows.all()), total

    async def knowledge_counts(self) -> dict[str, object]:
        documents, active_documents, entities, last_import = (
            await self.session.execute(
                select(
                    select(func.count(Document.id)).scalar_subquery(),
                    select(func.count(Document.id)).where(Document.is_active.is_(True)).scalar_subquery(),
                    select(func.count(EntityCandidate.id)).scalar_subquery(),
                    select(func.max(Document.fetched_at)).scalar_subquery(),
                )
            )
        ).one()
        return {
            "documents": int(documents),
            "active_documents": int(active_documents),
            "entity_candidates": int(entities),
            "last_import_at": last_import,
        }
