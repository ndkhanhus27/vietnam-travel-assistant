from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, Conversation, User


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
    ) -> tuple[list[tuple[User, int, int]], int]:
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
        rows = await self.session.execute(
            select(
                User,
                conversation_count.label("conversation_count"),
                run_count.label("run_count"),
            )
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = int(
            (await self.session.execute(select(func.count(User.id))))
            .scalar_one()
        )
        return [
            (user, int(conversations), int(runs))
            for user, conversations, runs in rows.all()
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

    async def list_agent_runs(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[AgentRun, str, str | None]], int]:
        rows = await self.session.execute(
            select(AgentRun, User.email, User.display_name)
            .join(
                Conversation,
                Conversation.id == AgentRun.conversation_id,
            )
            .join(User, User.id == Conversation.user_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = int(
            (await self.session.execute(select(func.count(AgentRun.id))))
            .scalar_one()
        )
        return list(rows.all()), total
