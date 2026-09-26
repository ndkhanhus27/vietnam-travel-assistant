from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from pipeline.agents.schemas import (
    AgentResponse,
    AgentResponseType,
    ClarificationAnswerType,
    ClarificationDecision,
    ClarificationField,
    ClarificationOption,
    ClarificationRequest,
    ConstraintSource,
    ExtractedConstraint,
    Intent,
    RequirementLevel,
    SubTask,
    ToolName,
)


# ============================================================
# INTERNAL REQUIREMENT MODEL
# ============================================================


@dataclass(frozen=True)
class RequirementSpec:
    """
    Internal deterministic requirement.

    Không expose trực tiếp ra frontend.
    """

    field_key: str

    level: RequirementLevel

    priority: int

    answer_type: ClarificationAnswerType

    question: str

    options: tuple[
        tuple[str, str],
        ...
    ] = ()

    allow_free_text: bool = True

    reason: str | None = None


# ============================================================
# FIELD KEY NORMALIZATION
# ============================================================


FIELD_ALIASES: dict[
    str,
    set[str],
] = {
    "destination": {
        "destination",
        "location",
        "place",
        "city",
        "target_location",
    },

    "origin": {
        "origin",
        "from",
        "departure_location",
        "start_location",
    },

    "trip_duration": {
        "trip_duration",
        "trip_duration_days",
        "duration",
        "duration_days",
        "days",
    },

    "travel_date": {
        "travel_date",
        "departure_date",
        "date",
        "trip_date",
        "start_date",
    },

    "budget": {
        "budget",
        "total_budget",
        "trip_budget",
    },

    "travelers": {
        "travelers",
        "traveler_count",
        "people",
        "party_size",
    },

    "comparison_targets": {
        "comparison_targets",
        "compare_entities",
        "targets",
    },
}


# ============================================================
# FIELD CATALOG
# ============================================================


FIELD_CATALOG: dict[
    str,
    RequirementSpec,
] = {
    "destination": RequirementSpec(
        field_key="destination",

        level=(
            RequirementLevel
            .BLOCKING
        ),

        priority=100,

        answer_type=(
            ClarificationAnswerType
            .FREE_TEXT
        ),

        question=(
            "Bạn muốn áp dụng yêu cầu này "
            "cho địa điểm nào?"
        ),

        reason=(
            "Chưa xác định được địa điểm "
            "cần xử lý."
        ),
    ),

    "origin": RequirementSpec(
        field_key="origin",

        level=(
            RequirementLevel
            .BLOCKING
        ),

        priority=100,

        answer_type=(
            ClarificationAnswerType
            .FREE_TEXT
        ),

        question=(
            "Bạn xuất phát từ đâu?"
        ),

        reason=(
            "Cần điểm xuất phát để xử lý "
            "yêu cầu di chuyển."
        ),
    ),

    "trip_duration": RequirementSpec(
        field_key="trip_duration",

        level=(
            RequirementLevel
            .BLOCKING
        ),

        priority=95,

        answer_type=(
            ClarificationAnswerType
            .SINGLE_CHOICE
        ),

        question=(
            "Bạn dự định chuyến đi "
            "kéo dài bao lâu?"
        ),

        options=(
            (
                "2 ngày 1 đêm",
                "2 ngày 1 đêm",
            ),
            (
                "3 ngày 2 đêm",
                "3 ngày 2 đêm",
            ),
            (
                "4 ngày 3 đêm",
                "4 ngày 3 đêm",
            ),
        ),

        reason=(
            "Thời lượng chuyến đi ảnh hưởng "
            "trực tiếp đến cách xây dựng lịch trình."
        ),
    ),

    "travel_date": RequirementSpec(
        field_key="travel_date",

        level=(
            RequirementLevel
            .IMPORTANT
        ),

        priority=65,

        answer_type=(
            ClarificationAnswerType
            .DATE
        ),

        question=(
            "Bạn dự định đi vào ngày nào?"
        ),

        reason=(
            "Ngày đi có thể ảnh hưởng thời tiết "
            "và thông tin có tính thời điểm."
        ),
    ),

    "budget": RequirementSpec(
        field_key="budget",

        level=(
            RequirementLevel
            .IMPORTANT
        ),

        priority=55,

        answer_type=(
            ClarificationAnswerType
            .NUMBER
        ),

        question=(
            "Ngân sách dự kiến cho chuyến đi "
            "của bạn khoảng bao nhiêu?"
        ),

        reason=(
            "Ngân sách giúp điều chỉnh "
            "các gợi ý phù hợp hơn."
        ),
    ),

    "travelers": RequirementSpec(
        field_key="travelers",

        level=(
            RequirementLevel
            .IMPORTANT
        ),

        priority=50,

        answer_type=(
            ClarificationAnswerType
            .NUMBER
        ),

        question=(
            "Chuyến đi có bao nhiêu người?"
        ),

        reason=(
            "Số người có thể ảnh hưởng "
            "ngân sách và lịch trình."
        ),
    ),

    "comparison_targets": RequirementSpec(
        field_key=(
            "comparison_targets"
        ),

        level=(
            RequirementLevel
            .BLOCKING
        ),

        priority=100,

        answer_type=(
            ClarificationAnswerType
            .FREE_TEXT
        ),

        question=(
            "Bạn muốn so sánh "
            "những địa điểm nào?"
        ),

        reason=(
            "Cần ít nhất hai đối tượng "
            "để thực hiện so sánh."
        ),
    ),
}


# ============================================================
# INTENT REQUIREMENTS
# ============================================================


INTENT_REQUIREMENTS: dict[
    Intent,
    tuple[str, ...],
] = {
    Intent.FACTUAL_TRAVEL: (
        "destination",
    ),

    Intent.RECOMMENDATION: (
        "destination",
    ),

    Intent.COMPARISON: (
        "comparison_targets",
    ),

    Intent.ITINERARY: (
        "destination",
        "trip_duration",
        "travel_date",
        "travelers",
        "budget",
    ),

    Intent.WEATHER: (
        "destination",
    ),

    Intent.ROUTING: (
        "origin",
        "destination",
    ),
}


# ============================================================
# TOOL REQUIREMENTS
# ============================================================


TOOL_REQUIREMENTS: dict[
    ToolName,
    tuple[str, ...],
] = {
    ToolName.WEATHER: (
        "destination",
    ),

    ToolName.ROUTING: (
        "origin",
        "destination",
    ),
}


# ============================================================
# CLARIFICATION POLICY
# ============================================================


class ClarificationPolicy:
    """
    Deterministic clarification policy.

    Responsibilities:

        - normalize known constraints
        - incorporate entities
        - incorporate already-populated tool arguments
        - determine missing blocking fields
        - track important-but-non-blocking fields
        - incorporate ambiguity candidates
        - ask only the highest priority 1-2 questions

    Không:
        - gọi LLM
        - execute tools
        - modify Planner output
        - guess missing values
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
        max_fields_per_turn: int = 2,
    ) -> None:

        if (
            max_fields_per_turn < 1
            or max_fields_per_turn > 2
        ):

            raise ValueError(
                "max_fields_per_turn must "
                "be between 1 and 2."
            )

        self.max_fields_per_turn = (
            max_fields_per_turn
        )

    # ========================================================
    # KEYS
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

    @classmethod
    def _canonical_key(
        cls,
        key: str,
    ) -> str:

        normalized = (
            cls._normalize_key(
                key
            )
        )

        for (
            canonical,
            aliases,
        ) in FIELD_ALIASES.items():

            if (
                normalized
                == canonical
                or normalized
                in aliases
            ):

                return canonical

        return normalized

    # ========================================================
    # VALUE CHECK
    # ========================================================

    @staticmethod
    def _has_value(
        value: Any,
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

            return bool(
                value
            )

        return True

    # ========================================================
    # CONSTRAINT RESOLUTION
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

    def _build_constraint_map(
        self,
        constraints: Iterable[
            ExtractedConstraint
        ],
    ) -> dict[
        str,
        ExtractedConstraint,
    ]:

        result: dict[
            str,
            ExtractedConstraint,
        ] = {}

        for constraint in constraints:

            key = (
                self._canonical_key(
                    constraint.key
                )
            )

            current = (
                result.get(
                    key
                )
            )

            if current is None:

                result[key] = constraint

                continue

            if (
                self._constraint_score(
                    constraint
                )
                >
                self._constraint_score(
                    current
                )
            ):

                result[key] = constraint

        return result

    # ========================================================
    # DERIVED CONTEXT
    # ========================================================

    def _augment_from_entities(
        self,
        *,
        intent: Intent,
        entities: list[str],
        known: dict[
            str,
            ExtractedConstraint,
        ],
    ) -> None:
        """
        Entity extraction đã xác định được location/entity
        thì không cần hỏi lại user.

        Chỉ derive deterministic facts.
        """

        clean_entities = [
            entity.strip()
            for entity
            in entities
            if entity.strip()
        ]

        if (
            "destination"
            not in known
            and len(clean_entities) == 1
        ):

            known[
                "destination"
            ] = ExtractedConstraint(
                key="destination",

                value=clean_entities[0],

                source=(
                    ConstraintSource
                    .INFERRED
                ),

                explicit=False,
            )

        if (
            intent
            == Intent.COMPARISON
            and len(clean_entities) >= 2
            and "comparison_targets"
            not in known
        ):

            known[
                "comparison_targets"
            ] = ExtractedConstraint(
                key=(
                    "comparison_targets"
                ),

                value=clean_entities,

                source=(
                    ConstraintSource
                    .INFERRED
                ),

                explicit=False,
            )

    def _augment_from_subtasks(
        self,
        *,
        subtasks: list[SubTask],
        known: dict[
            str,
            ExtractedConstraint,
        ],
    ) -> None:
        """
        Nếu Planner đã tạo tool arguments hợp lệ,
        clarification không được hỏi lại field đó.
        """

        for task in subtasks:

            args = (
                task.arguments
                or {}
            )

            # -----------------------------------------------
            # WEATHER
            # -----------------------------------------------

            if (
                task.tool
                == ToolName.WEATHER
            ):

                location = (
                    args.get(
                        "location"
                    )
                )

                if (
                    self._has_value(
                        location
                    )
                    and "destination"
                    not in known
                ):

                    known[
                        "destination"
                    ] = ExtractedConstraint(
                        key="destination",

                        value=str(
                            location
                        ),

                        source=(
                            ConstraintSource
                            .INFERRED
                        ),

                        explicit=False,
                    )

            # -----------------------------------------------
            # ROUTING
            # -----------------------------------------------

            elif (
                task.tool
                == ToolName.ROUTING
            ):

                origin = (
                    args.get(
                        "origin"
                    )
                )

                destination = (
                    args.get(
                        "destination"
                    )
                )

                if (
                    self._has_value(
                        origin
                    )
                    and "origin"
                    not in known
                ):

                    known[
                        "origin"
                    ] = ExtractedConstraint(
                        key="origin",

                        value=str(
                            origin
                        ),

                        source=(
                            ConstraintSource
                            .INFERRED
                        ),

                        explicit=False,
                    )

                if (
                    self._has_value(
                        destination
                    )
                    and "destination"
                    not in known
                ):

                    known[
                        "destination"
                    ] = ExtractedConstraint(
                        key="destination",

                        value=str(
                            destination
                        ),

                        source=(
                            ConstraintSource
                            .INFERRED
                        ),

                        explicit=False,
                    )

    # ========================================================
    # REQUIREMENTS
    # ========================================================

    @staticmethod
    def _stronger_level(
        a: RequirementLevel,
        b: RequirementLevel,
    ) -> RequirementLevel:

        order = {
            RequirementLevel.OPTIONAL: 0,
            RequirementLevel.IMPORTANT: 1,
            RequirementLevel.BLOCKING: 2,
        }

        if order[a] >= order[b]:
            return a

        return b

    def _requirements_for(
        self,
        *,
        intent: Intent,
        subtasks: list[SubTask],
    ) -> dict[
        str,
        RequirementSpec,
    ]:

        field_keys: list[str] = list(
            INTENT_REQUIREMENTS.get(
                intent,
                (),
            )
        )

        for task in subtasks:

            field_keys.extend(
                TOOL_REQUIREMENTS.get(
                    task.tool,
                    (),
                )
            )

        requirements: dict[
            str,
            RequirementSpec,
        ] = {}

        for field_key in field_keys:

            spec = (
                FIELD_CATALOG.get(
                    field_key
                )
            )

            if spec is None:
                continue

            existing = (
                requirements.get(
                    field_key
                )
            )

            if existing is None:

                requirements[
                    field_key
                ] = spec

                continue

            level = (
                self._stronger_level(
                    existing.level,
                    spec.level,
                )
            )

            priority = max(
                existing.priority,
                spec.priority,
            )

            requirements[
                field_key
            ] = RequirementSpec(
                field_key=(
                    existing.field_key
                ),

                level=level,

                priority=priority,

                answer_type=(
                    existing.answer_type
                ),

                question=(
                    existing.question
                ),

                options=(
                    existing.options
                ),

                allow_free_text=(
                    existing
                    .allow_free_text
                ),

                reason=(
                    existing.reason
                ),
            )

        return requirements

    # ========================================================
    # MISSING
    # ========================================================

    def _is_missing(
        self,
        *,
        field_key: str,
        known: dict[
            str,
            ExtractedConstraint,
        ],
    ) -> bool:

        constraint = (
            known.get(
                field_key
            )
        )

        if constraint is None:
            return True

        value = constraint.value

        if not self._has_value(
            value
        ):
            return True

        # Comparison cần ít nhất 2 targets.
        if (
            field_key
            == "comparison_targets"
        ):

            if isinstance(
                value,
                list,
            ):

                return (
                    len(value)
                    < 2
                )

            return True

        return False

    # ========================================================
    # FIELD BUILDER
    # ========================================================

    @staticmethod
    def _field_from_spec(
        spec: RequirementSpec,
    ) -> ClarificationField:

        options = [
            ClarificationOption(
                label=label,
                value=value,
            )
            for (
                label,
                value,
            )
            in spec.options
        ]

        return ClarificationField(
            key=(
                spec.field_key
            ),

            question=(
                spec.question
            ),

            answer_type=(
                spec.answer_type
            ),

            options=options,

            requirement=(
                spec.level
            ),
        )

    @classmethod
    def _field_priority(
        cls,
        field: ClarificationField,
    ) -> int:
        """
        Keep policy priority internal instead of exposing it through
        the frontend clarification contract.
        """

        key = cls._canonical_key(
            field.key
        )

        spec = FIELD_CATALOG.get(
            key
        )

        if spec is not None:
            return spec.priority

        return {
            RequirementLevel.BLOCKING: 100,
            RequirementLevel.IMPORTANT: 50,
            RequirementLevel.OPTIONAL: 0,
        }[field.requirement]

    # ========================================================
    # AMBIGUITY
    # ========================================================

    def _normalize_ambiguity_fields(
        self,
        fields: list[
            ClarificationField
        ]
        | None,
    ) -> list[
        ClarificationField
    ]:
        """
        Planner/entity resolver có thể phát hiện ambiguity
        không thể biểu diễn chỉ bằng "missing field".

        Ví dụ:
            "chỗ đó"
            "Hồ X"
            entity có nhiều candidate
            conflicting dates

        Policy nhận các candidate đó và ưu tiên cùng
        với missing blocking fields.
        """

        if not fields:
            return []

        result: list[
            ClarificationField
        ] = []

        seen: set[str] = set()

        for field in fields:

            key = (
                self._canonical_key(
                    field.key
                )
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            if (
                key
                != field.key
            ):

                field = (
                    field.model_copy(
                        update={
                            "key": key,
                        }
                    )
                )

            result.append(
                field
            )

        return result

    # ========================================================
    # PUBLIC
    # ========================================================

    def evaluate(
        self,
        *,
        intent: Intent,
        constraints: list[
            ExtractedConstraint
        ],
        entities: list[str],
        subtasks: list[SubTask],
        ambiguity_fields: list[
            ClarificationField
        ]
        | None = None,
    ) -> ClarificationDecision:

        # ====================================================
        # KNOWN CONTEXT
        # ====================================================

        known = (
            self._build_constraint_map(
                constraints
            )
        )

        self._augment_from_entities(
            intent=intent,
            entities=entities,
            known=known,
        )

        self._augment_from_subtasks(
            subtasks=subtasks,
            known=known,
        )

        # ====================================================
        # REQUIREMENTS
        # ====================================================

        requirements = (
            self._requirements_for(
                intent=intent,
                subtasks=subtasks,
            )
        )

        blocking_fields: list[
            ClarificationField
        ] = []

        important_missing: list[
            str
        ] = []

        for (
            field_key,
            spec,
        ) in requirements.items():

            if not self._is_missing(
                field_key=field_key,
                known=known,
            ):

                continue

            if (
                spec.level
                == RequirementLevel
                .BLOCKING
            ):

                blocking_fields.append(
                    self._field_from_spec(
                        spec
                    )
                )

            elif (
                spec.level
                == RequirementLevel
                .IMPORTANT
            ):

                important_missing.append(
                    field_key
                )

        # ====================================================
        # EXPLICIT AMBIGUITIES
        # ====================================================

        ambiguity_candidates = (
            self
            ._normalize_ambiguity_fields(
                ambiguity_fields
            )
        )

        ask_candidates: list[
            ClarificationField
        ] = []

        ask_candidates.extend(
            blocking_fields
        )

        # Ambiguity được upstream phát hiện rõ ràng
        # thì có thể blocking conversation dù value tồn tại.
        for field in ambiguity_candidates:

            if (
                field.requirement
                == RequirementLevel.OPTIONAL
            ):
                continue

            ask_candidates.append(
                field
            )

        # ====================================================
        # DEDUPE
        # ====================================================

        deduped: dict[
            str,
            ClarificationField,
        ] = {}

        for field in ask_candidates:

            key = (
                self._canonical_key(
                    field.key
                )
            )

            current = (
                deduped.get(
                    key
                )
            )

            if (
                current is None
                or self._field_priority(
                    field
                )
                > self._field_priority(
                    current
                )
            ):

                if (
                    field.key
                    != key
                ):

                    field = (
                        field.model_copy(
                            update={
                                "key": key,
                            }
                        )
                    )

                deduped[key] = field

        selected = sorted(
            deduped.values(),

            key=lambda item: (
                -self._field_priority(
                    item
                ),
                item.key,
            ),
        )[
            :self.max_fields_per_turn
        ]

        # ====================================================
        # NO CLARIFICATION
        # ====================================================

        if not selected:

            return ClarificationDecision(
                clarification=None,

                blocking_fields=[],

                important_missing_fields=(
                    [
                        self._field_from_spec(
                            requirements[key]
                        )
                        for key
                        in sorted(
                            set(
                                important_missing
                            )
                        )
                    ]
                ),
            )

        # ====================================================
        # CLARIFICATION REQUEST
        # ====================================================

        message = (
            "Mình cần thêm một thông tin "
            "để xử lý yêu cầu chính xác hơn."
            if len(selected) == 1
            else
            "Mình cần thêm một vài thông tin "
            "để xử lý yêu cầu chính xác hơn."
        )

        request = (
            ClarificationRequest(
                question=message,

                fields=selected,
            )
        )

        return ClarificationDecision(
            clarification=request,

            blocking_fields=[
                field
                for field
                in selected
                if (
                    field.requirement
                    == RequirementLevel
                    .BLOCKING
                )
            ],

            important_missing_fields=(
                [
                    self._field_from_spec(
                        requirements[key]
                    )
                    for key
                    in sorted(
                        set(
                            important_missing
                        )
                    )
                ]
            ),
        )


# ============================================================
# FINAL RESPONSE BUILDER
# ============================================================


def build_clarification_response(
    decision: ClarificationDecision,
) -> AgentResponse:
    """
    Convert internal policy decision into public AgentResponse.

    FastAPI/frontend sau này chỉ cần đọc AgentResponse.
    """

    if (
        decision.clarification
        is None
    ):

        raise ValueError(
            "Cannot build clarification response "
            "when clarification is not needed."
        )

    return AgentResponse(
        response_type=(
            AgentResponseType
            .CLARIFICATION
        ),

        answer="",

        clarification=(
            decision.clarification
        ),

        citations=[],

        suggested_followups=[],

        degraded=False,
    )
