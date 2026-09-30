from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AgentRun, Message
from app.db.repositories.conversations import ConversationRepository
from app.services.context_adapter import (
    build_conversation_context,
    serialize_conversation_context,
)
from pipeline.agents.context import ContextBuilder, ConversationContext
from pipeline.agents.schemas import AgentResponse, AgentResponseType
from pipeline.agents.state import AgentState


logger = logging.getLogger(__name__)

MAX_CHAT_MESSAGE_LENGTH = 10_000
SAFE_WORKFLOW_ERROR_CODE = "WORKFLOW_ERROR"
SAFE_WORKFLOW_ERROR_MESSAGE = "Travel workflow execution failed"


class WorkflowRunner(Protocol):
    async def run(
        self,
        query: str,
        *,
        context: ConversationContext | None = None,
    ) -> AgentState: ...


class ChatError(Exception):
    """Base exception for chat use cases."""


class InvalidChatMessageError(ChatError):
    """Raised when a user message is empty or too large."""


class ConversationNotFoundError(ChatError):
    """Raised for missing and non-owned conversations alike."""


class ChatWorkflowError(ChatError):
    """Raised after a failed workflow run is durably recorded."""


@dataclass(frozen=True, slots=True)
class ChatResult:
    user_message: Message
    assistant_message: Message
    agent_run: AgentRun
    response: AgentResponse


@dataclass(frozen=True, slots=True)
class ChatStreamEvent:
    event: str
    data: dict[str, Any] | ChatResult


@dataclass(frozen=True, slots=True)
class _PreparedChat:
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    content: str
    context: ConversationContext
    user_message: Message
    agent_run_id: uuid.UUID


class ChatService:
    def __init__(
        self,
        session: AsyncSession,
        workflow: WorkflowRunner,
        *,
        repository: ConversationRepository | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or ConversationRepository(session)
        self.workflow = workflow
        self.context_builder = (
            context_builder
            or getattr(workflow, "context_builder", None)
            or ContextBuilder()
        )

    async def send_message(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
    ) -> ChatResult:
        prepared = await self._prepare_message(
            user_id=user_id,
            conversation_id=conversation_id,
            content=content,
        )
        return await self._execute_message(prepared)

    async def stream_message(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
    ) -> AsyncIterator[ChatStreamEvent]:
        prepared = await self._prepare_message(
            user_id=user_id,
            conversation_id=conversation_id,
            content=content,
        )
        return self._stream_prepared(prepared)

    async def _prepare_message(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
    ) -> _PreparedChat:
        normalized_content = _normalize_message(content)

        try:
            conversation = await self.repository.get_conversation_by_id(
                conversation_id,
                user_id,
            )
            if conversation is None:
                raise ConversationNotFoundError("Conversation not found")

            history = await self.repository.get_recent_messages(
                conversation_id,
                user_id,
                self.context_builder.max_recent_messages,
            )
            context = build_conversation_context(
                messages=history,
                context_builder=self.context_builder,
                stored_state=conversation.context_state,
            )
            if conversation.title is None and not history:
                await self.repository.update_conversation_title(
                    conversation,
                    _conversation_title(normalized_content),
                )

            user_message = await self.repository.add_message(
                conversation_id=conversation_id,
                role="user",
                content=normalized_content,
            )
            agent_run = await self.repository.create_agent_run(
                conversation_id=conversation_id,
                user_message_id=user_message.id,
                model_name=settings.gemini_model,
            )
            await self.session.commit()
            return _PreparedChat(
                user_id=user_id,
                conversation_id=conversation_id,
                content=normalized_content,
                context=context,
                user_message=user_message,
                agent_run_id=agent_run.id,
            )
        except Exception:
            await self.session.rollback()
            raise

    async def _execute_message(
        self,
        prepared: _PreparedChat,
        *,
        progress_sink: Callable[[ChatStreamEvent], Awaitable[None]] | None = None,
    ) -> ChatResult:
        started_at = time.perf_counter()
        try:
            state = await self._run_workflow(
                prepared,
                progress_sink=progress_sink,
            )
            latency_ms = _elapsed_ms(started_at)
            return await self._persist_success(
                user_id=prepared.user_id,
                conversation_id=prepared.conversation_id,
                user_message=prepared.user_message,
                agent_run_id=prepared.agent_run_id,
                state=state,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = _elapsed_ms(started_at)
            await self._persist_failure(
                conversation_id=prepared.conversation_id,
                agent_run_id=prepared.agent_run_id,
                latency_ms=latency_ms,
            )
            logger.exception(
                "Chat workflow failed",
                extra={
                    "agent_run_id": str(prepared.agent_run_id),
                    "conversation_id": str(prepared.conversation_id),
                    "status": "failed",
                    "latency_ms": latency_ms,
                    "error_code": SAFE_WORKFLOW_ERROR_CODE,
                },
            )
            raise ChatWorkflowError(SAFE_WORKFLOW_ERROR_MESSAGE) from exc

    async def _run_workflow(
        self,
        prepared: _PreparedChat,
        *,
        progress_sink: Callable[[ChatStreamEvent], Awaitable[None]] | None,
    ) -> AgentState:
        stream = getattr(self.workflow, "stream", None)
        if progress_sink is None or not callable(stream):
            return await self.workflow.run(
                prepared.content,
                context=prepared.context,
            )

        final_state: AgentState | None = None
        async for item_type, payload in stream(
            prepared.content,
            context=prepared.context,
        ):
            if item_type == "progress" and isinstance(payload, dict):
                event = _workflow_progress_event(payload)
                if event is not None:
                    await progress_sink(event)
            elif item_type == "result" and isinstance(payload, dict):
                final_state = cast(AgentState, payload)

        if final_state is None:
            raise ValueError("Workflow stream returned no final state")
        return final_state

    async def _stream_prepared(
        self,
        prepared: _PreparedChat,
    ) -> AsyncIterator[ChatStreamEvent]:
        queue: asyncio.Queue[ChatStreamEvent | None] = asyncio.Queue(maxsize=32)

        async def produce() -> None:
            try:
                result = await self._execute_message(
                    prepared,
                    progress_sink=queue.put,
                )
                await queue.put(ChatStreamEvent("completed", result))
            except ChatWorkflowError:
                await queue.put(
                    ChatStreamEvent(
                        "error",
                        {
                            "code": "CHAT_WORKFLOW_ERROR",
                            "message": "Unable to complete the assistant response.",
                        },
                    )
                )
            finally:
                await queue.put(None)

        producer = asyncio.create_task(produce())
        try:
            yield ChatStreamEvent(
                "connected",
                {"conversation_id": str(prepared.conversation_id)},
            )
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            await _finish_stream_producer(producer, queue)

    async def _persist_success(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_message: Message,
        agent_run_id: uuid.UUID,
        state: AgentState,
        latency_ms: int,
    ) -> ChatResult:
        try:
            response = state.get("response")
            if not isinstance(response, AgentResponse):
                raise ValueError("Workflow returned no usable response")
            final_context = state.get("conversation_context")
            if not isinstance(final_context, ConversationContext):
                raise ValueError("Workflow returned no conversation context")

            answer = _response_content(response, final_context)
            if not answer:
                raise ValueError("Workflow returned an empty response")

            conversation = await self.repository.get_conversation_by_id(
                conversation_id,
                user_id,
            )
            agent_run = await self.repository.get_agent_run_by_id(
                agent_run_id,
                conversation_id,
            )
            if conversation is None or agent_run is None:
                raise LookupError("Chat persistence state no longer exists")

            plan = state.get("plan")
            reasoner_output = state.get("reasoner_output")
            assistant_message = await self.repository.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                intent=_enum_value(response.intent),
                citations=[
                    citation.model_dump(mode="json")
                    for citation in response.citations
                ],
                warnings=_response_warnings(reasoner_output),
            )
            await self.repository.update_conversation_context(
                conversation,
                serialize_conversation_context(
                    final_context,
                    last_sequence_no=assistant_message.sequence_no,
                ),
            )
            degraded = bool(response.degraded) or bool(
                reasoner_output is not None
                and getattr(reasoner_output, "degraded", False)
            )
            await self.repository.complete_agent_run(
                agent_run,
                status="degraded" if degraded else "success",
                assistant_message_id=assistant_message.id,
                latency_ms=latency_ms,
                retry_count=int(state.get("retry_count", 0)),
                tools_used=_tools_used(state),
                intent=_enum_value(
                    response.intent or getattr(plan, "intent", None)
                ),
                retrieval_mode=_enum_value(
                    getattr(plan, "retrieval_mode", None)
                ),
                model_name=settings.gemini_model,
                completed_at=datetime.now(timezone.utc),
            )
            await self.session.commit()

            logger.info(
                "Chat workflow completed",
                extra={
                    "agent_run_id": str(agent_run.id),
                    "conversation_id": str(conversation_id),
                    "status": agent_run.status,
                    "latency_ms": latency_ms,
                    "intent": agent_run.intent,
                    "tools_used": agent_run.tools_used,
                },
            )
            return ChatResult(
                user_message=user_message,
                assistant_message=assistant_message,
                agent_run=agent_run,
                response=response,
            )
        except Exception:
            await self.session.rollback()
            raise

    async def _persist_failure(
        self,
        *,
        conversation_id: uuid.UUID,
        agent_run_id: uuid.UUID,
        latency_ms: int,
    ) -> None:
        try:
            agent_run = await self.repository.get_agent_run_by_id(
                agent_run_id,
                conversation_id,
            )
            if agent_run is None:
                raise LookupError("Agent run no longer exists")
            await self.repository.complete_agent_run(
                agent_run,
                status="failed",
                latency_ms=latency_ms,
                error_code=SAFE_WORKFLOW_ERROR_CODE,
                error_message=SAFE_WORKFLOW_ERROR_MESSAGE,
                completed_at=datetime.now(timezone.utc),
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            logger.exception(
                "Could not persist chat workflow failure",
                extra={
                    "agent_run_id": str(agent_run_id),
                    "conversation_id": str(conversation_id),
                },
            )


def _normalize_message(content: str) -> str:
    if not isinstance(content, str):
        raise InvalidChatMessageError("Message content must be a string")

    normalized = content.strip()
    if not normalized:
        raise InvalidChatMessageError("Message must not be empty")
    if len(normalized) > MAX_CHAT_MESSAGE_LENGTH:
        raise InvalidChatMessageError(
            f"Message must not exceed {MAX_CHAT_MESSAGE_LENGTH} characters"
        )
    return normalized


def _conversation_title(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip()[:60]


def _response_content(
    response: AgentResponse,
    context: ConversationContext,
) -> str:
    if response.answer.strip():
        return response.answer.strip()
    if response.response_type == AgentResponseType.CLARIFICATION:
        for message in reversed(context.recent_messages):
            if message.role.value == "assistant" and message.content.strip():
                return message.content.strip()
    return ""


def _response_warnings(reasoner_output: object | None) -> list[str]:
    if reasoner_output is None:
        return []
    values = [
        *getattr(reasoner_output, "warnings", []),
        *getattr(reasoner_output, "limitations", []),
    ]
    return list(dict.fromkeys(value for value in values if value))


def _tools_used(state: AgentState) -> list[str]:
    tools: list[str] = []
    for observation in state.get("observations", []):
        value = _enum_value(observation.tool)
        if value and value not in tools:
            tools.append(value)
    response = state.get("response")
    if isinstance(response, AgentResponse):
        for tool in response.used_tools:
            value = _enum_value(tool)
            if value and value not in tools:
                tools.append(value)
    return tools


def _enum_value(value: object | None) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", value)
    return str(enum_value)


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _workflow_progress_event(
    payload: dict[str, Any],
) -> ChatStreamEvent | None:
    event_type = payload.get("type")
    if event_type == "stage":
        stage = payload.get("stage")
        message = payload.get("message")
        if not isinstance(stage, str) or not isinstance(message, str):
            return None
        return ChatStreamEvent(
            "stage",
            {"stage": stage, "message": message},
        )
    if event_type == "tool":
        tool = payload.get("tool")
        status = payload.get("status")
        if not isinstance(tool, str) or not isinstance(status, str):
            return None
        data = {"tool": tool, "status": status}
        task_id = payload.get("task_id")
        if isinstance(task_id, str):
            data["task_id"] = task_id
        return ChatStreamEvent("tool", data)
    return None


async def _finish_stream_producer(
    producer: asyncio.Task[None],
    queue: asyncio.Queue[ChatStreamEvent | None],
) -> None:
    current = asyncio.current_task()
    while not producer.done():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        if current is not None and current.cancelling():
            current.uncancel()
        try:
            await asyncio.wait_for(asyncio.shield(producer), timeout=0.1)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            continue

    await producer
