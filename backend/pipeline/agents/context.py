from __future__ import annotations

from enum import Enum

from pydantic import Field

from pipeline.agents.schemas import (
    ClarificationRequest,
    ConstraintSource,
    ExecutionPlan,
    ExtractedConstraint,
    Intent,
    StrictModel,
)


# ============================================================
# CONVERSATION MESSAGE
# ============================================================


class ConversationRole(
    str,
    Enum,
):
    USER = "user"
    ASSISTANT = "assistant"


class ContextMessage(
    StrictModel
):
    """
    Message tối giản dùng để build conversational context.

    Đây chưa phải PostgreSQL Message model.
    """

    role: ConversationRole

    content: str = Field(
        min_length=1
    )


# ============================================================
# PENDING CLARIFICATION
# ============================================================


class PendingClarification(
    StrictModel
):
    """
    Clarification đang chờ user trả lời.

    original_query:
        Yêu cầu ban đầu dẫn tới clarification.

    original_goal:
        Goal Planner đã hiểu.

    original_intent / original_entities:
        Semantic request đang hoạt động trước khi hỏi làm rõ.

    known_constraints:
        Những gì agent đã biết tại thời điểm hỏi.
    """

    original_query: str = Field(
        min_length=1
    )

    original_goal: str | None = None

    original_intent: Intent | None = None

    original_entities: list[str] = Field(
        default_factory=list
    )

    request: ClarificationRequest

    known_constraints: list[
        ExtractedConstraint
    ] = Field(
        default_factory=list
    )


# ============================================================
# CONVERSATION CONTEXT
# ============================================================


class ConversationContext(
    StrictModel
):
    """
    Context compact truyền vào Planner.

    Sau này:
        PostgreSQL
            ↓
        Redis
            ↓
        ContextBuilder
            ↓
        ConversationContext

    Không chứa toàn bộ LangGraph state.
    """

    summary: str | None = None

    recent_messages: list[
        ContextMessage
    ] = Field(
        default_factory=list
    )

    known_constraints: list[
        ExtractedConstraint
    ] = Field(
        default_factory=list
    )

    pending_clarification: (
        PendingClarification
        | None
    ) = None


# ============================================================
# CONTEXT BUILDER
# ============================================================


class ContextBuilder:
    """
    Deterministic conversation context manager.

    Responsibilities:

        - preserve known constraints across turns
        - merge new constraints
        - apply precedence
        - preserve pending clarification
        - keep recent message window bounded

    Không:
        - gọi LLM
        - query database
        - query Redis
        - execute agent tools
    """

    _SOURCE_PRIORITY = {
        ConstraintSource.INFERRED: 10,

        ConstraintSource.CONVERSATION: 20,

        ConstraintSource.CLARIFICATION: 30,

        ConstraintSource.CURRENT_MESSAGE: 40,
    }

    def __init__(
        self,
        *,
        max_recent_messages: int = 12,
    ) -> None:

        if max_recent_messages < 1:

            raise ValueError(
                "max_recent_messages "
                "must be >= 1."
            )

        self.max_recent_messages = (
            max_recent_messages
        )

    # ========================================================
    # KEY NORMALIZATION
    # ========================================================

    @staticmethod
    def _normalize_key(
        key: str,
    ) -> str:

        return (
            key
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )

    # ========================================================
    # VALUE
    # ========================================================

    @staticmethod
    def _has_value(
        value,
    ) -> bool:

        if value is None:
            return False

        if isinstance(
            value,
            str,
        ):

            return bool(
                value.strip()
            )

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
                dict,
            ),
        ):

            return bool(value)

        return True

    # ========================================================
    # SCORE
    # ========================================================

    def _constraint_score(
        self,
        constraint: ExtractedConstraint,
    ) -> tuple[int, int]:

        source_score = (
            self._SOURCE_PRIORITY.get(
                constraint.source,
                0,
            )
        )

        explicit_score = (
            1
            if constraint.explicit
            else 0
        )

        return (
            source_score,
            explicit_score,
        )

    # ========================================================
    # CARRY FORWARD
    # ========================================================

    @staticmethod
    def _carry_forward(
        constraint: ExtractedConstraint,
    ) -> ExtractedConstraint:
        """
        Constraint từ turn trước trở thành
        conversation context.

        INFERRED vẫn giữ INFERRED để không nâng
        assumption thành user-provided fact.
        """

        if (
            constraint.source
            == ConstraintSource.INFERRED
        ):

            return constraint

        return constraint.model_copy(
            update={
                "source": (
                    ConstraintSource
                    .CONVERSATION
                ),
            }
        )

    # ========================================================
    # CURRENT TURN SOURCE
    # ========================================================

    @staticmethod
    def _current_turn_constraint(
        constraint: ExtractedConstraint,
        *,
        answering_clarification: bool,
    ) -> ExtractedConstraint:
        """
        Planner chỉ extract semantic values.

        ContextBuilder quyết định source dựa trên
        conversation state.
        """

        source = (
            ConstraintSource
            .CLARIFICATION

            if answering_clarification

            else ConstraintSource
            .CURRENT_MESSAGE
        )

        return constraint.model_copy(
            update={
                "source": source,
            }
        )

    # ========================================================
    # MERGE CONSTRAINTS
    # ========================================================

    def merge_constraints(
        self,
        *,
        previous: list[
            ExtractedConstraint
        ],
        current: list[
            ExtractedConstraint
        ],
        answering_clarification: bool,
    ) -> list[
        ExtractedConstraint
    ]:
        """
        Precedence:

            current explicit message
                >
            clarification answer
                >
            conversation context
                >
            inferred

        Latest constraint wins when priority ties.
        """

        merged: dict[
            str,
            ExtractedConstraint,
        ] = {}

        # ----------------------------------------------------
        # PREVIOUS
        # ----------------------------------------------------

        for item in previous:

            item = (
                self._carry_forward(
                    item
                )
            )

            if not self._has_value(
                item.value
            ):
                continue

            key = (
                self._normalize_key(
                    item.key
                )
            )

            merged[key] = (
                item.model_copy(
                    update={
                        "key": key,
                    }
                )
            )

        # ----------------------------------------------------
        # CURRENT
        # ----------------------------------------------------

        for item in current:

            if not self._has_value(
                item.value
            ):
                continue

            item = (
                self._current_turn_constraint(
                    item,
                    answering_clarification=(
                        answering_clarification
                    ),
                )
            )

            key = (
                self._normalize_key(
                    item.key
                )
            )

            item = item.model_copy(
                update={
                    "key": key,
                }
            )

            existing = (
                merged.get(
                    key
                )
            )

            if existing is None:

                merged[key] = item
                continue

            current_score = (
                self._constraint_score(
                    item
                )
            )

            existing_score = (
                self._constraint_score(
                    existing
                )
            )

            if (
                current_score
                >= existing_score
            ):

                # Latest value wins when
                # priority is equal.
                merged[key] = item

        return list(
            merged.values()
        )

    # ========================================================
    # RECENT MESSAGES
    # ========================================================

    def append_message(
        self,
        context: ConversationContext,
        *,
        role: ConversationRole,
        content: str,
    ) -> ConversationContext:

        content = content.strip()

        if not content:

            return context

        messages = [
            *context.recent_messages,

            ContextMessage(
                role=role,
                content=content,
            ),
        ]

        messages = messages[
            -self.max_recent_messages:
        ]

        return context.model_copy(
            update={
                "recent_messages": (
                    messages
                ),
            }
        )

    # ========================================================
    # PREPARE CONSTRAINTS FOR CURRENT TURN
    # ========================================================

    def prepare_constraints_for_turn(
        self,
        *,
        context: (
            ConversationContext
            | None
        ),
        current_constraints: list[
            ExtractedConstraint
        ],
    ) -> list[
        ExtractedConstraint
    ]:

        if context is None:

            return (
                self.merge_constraints(
                    previous=[],

                    current=(
                        current_constraints
                    ),

                    answering_clarification=False,
                )
            )

        return self.merge_constraints(
            previous=(
                context
                .known_constraints
            ),

            current=(
                current_constraints
            ),

            answering_clarification=(
                context
                .pending_clarification
                is not None
            ),
        )

    # ========================================================
    # UPDATE AFTER PLAN
    # ========================================================

    def update_after_plan(
        self,
        *,
        previous_context: (
            ConversationContext
            | None
        ),
        query: str,
        plan: ExecutionPlan,
    ) -> ConversationContext:
        """
        Update conversation context sau khi Planner
        đã xử lý current turn.

        plan.constraints phải là resolved constraint set của turn,
        không chỉ là current-message delta.
        """

        context = (
            previous_context
            if previous_context
            is not None
            else ConversationContext()
        )

        # ====================================================
        # USER MESSAGE
        # ====================================================

        context = self.append_message(
            context,

            role=(
                ConversationRole.USER
            ),

            content=query,
        )

        # ====================================================
        # CONSTRAINTS
        # ====================================================

        # ExecutionPlan.constraints is already the resolved, merged
        # constraint set produced by TravelPlanner for this turn.
        # Merging it again would incorrectly relabel carried values as
        # current-message or clarification values.
        merged_constraints = list(
            plan.constraints
        )

        # ====================================================
        # PENDING CLARIFICATION
        # ====================================================

        pending: (
            PendingClarification
            | None
        )

        if (
            plan.clarification
            is not None
        ):

            pending = (
                PendingClarification(
                    original_query=query,

                    original_goal=(
                        plan.goal
                    ),

                    original_intent=(
                        plan.intent
                    ),

                    original_entities=list(
                        plan.entities
                    ),

                    request=(
                        plan.clarification
                    ),

                    known_constraints=(
                        merged_constraints
                    ),
                )
            )

        else:

            # Planner đã resolve được yêu cầu.
            # Pending clarification cũ được clear.
            pending = None

        return context.model_copy(
            update={
                "known_constraints": (
                    merged_constraints
                ),

                "pending_clarification": (
                    pending
                ),
            }
        )

    # ========================================================
    # PLANNER PAYLOAD
    # ========================================================

    @staticmethod
    def planner_context_payload(
        context: (
            ConversationContext
            | None
        ),
    ) -> dict:
        """
        Compact JSON-safe payload cho Planner prompt.

        Không gửi object Python/raw state vào Gemini.
        """

        if context is None:

            return {
                "summary": None,

                "recent_messages": [],

                "known_constraints": [],

                "pending_clarification": (
                    None
                ),
            }

        pending = (
            context
            .pending_clarification
        )

        return {
            "summary": (
                context.summary
            ),

            "recent_messages": [
                {
                    "role": (
                        message.role.value
                    ),

                    "content": (
                        message.content
                    ),
                }

                for message
                in context.recent_messages
            ],

            "known_constraints": [
                item.model_dump(
                    mode="json"
                )

                for item
                in context.known_constraints
            ],

            "pending_clarification": (
                None
                if pending is None
                else {
                    "original_query": (
                        pending
                        .original_query
                    ),

                    "original_goal": (
                        pending
                        .original_goal
                    ),

                    "original_intent": (
                        None
                        if (
                            pending
                            .original_intent
                            is None
                        )
                        else (
                            pending
                            .original_intent
                            .value
                        )
                    ),

                    "original_entities": (
                        pending
                        .original_entities
                    ),

                    "request": (
                        pending
                        .request
                        .model_dump(
                            mode="json"
                        )
                    ),
                }
            ),
        }
