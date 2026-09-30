from __future__ import annotations

from typing import Any, Iterable

from app.db.models import Message
from pipeline.agents.context import (
    ContextBuilder,
    ConversationContext,
    ConversationRole,
)


CONTEXT_STATE_VERSION = 1


def build_conversation_context(
    *,
    messages: Iterable[Message],
    context_builder: ContextBuilder,
    stored_state: dict[str, Any] | None,
) -> ConversationContext:
    context, last_sequence_no = _load_stored_context(stored_state)

    for message in messages:
        if message.sequence_no <= last_sequence_no:
            continue
        if message.role not in {
            ConversationRole.USER.value,
            ConversationRole.ASSISTANT.value,
        }:
            continue
        context = context_builder.append_message(
            context,
            role=ConversationRole(message.role),
            content=message.content,
        )

    return context


def serialize_conversation_context(
    context: ConversationContext,
    *,
    last_sequence_no: int,
) -> dict[str, Any]:
    return {
        "version": CONTEXT_STATE_VERSION,
        "last_sequence_no": last_sequence_no,
        "context": context.model_dump(mode="json"),
    }


def _load_stored_context(
    stored_state: dict[str, Any] | None,
) -> tuple[ConversationContext, int]:
    if not stored_state:
        return ConversationContext(), 0

    if "context" in stored_state:
        context_data = stored_state.get("context")
        last_sequence_no = stored_state.get("last_sequence_no", 0)
    else:
        context_data = stored_state
        last_sequence_no = 0

    if not isinstance(context_data, dict):
        return ConversationContext(), 0
    if not isinstance(last_sequence_no, int) or last_sequence_no < 0:
        last_sequence_no = 0

    return ConversationContext.model_validate(context_data), last_sequence_no
