from __future__ import annotations

import argparse
import json
import logging
import re
import unicodedata
from typing import Any

from google.genai import types
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from app.core.config import settings

from pipeline.agents.clarification import (
    ClarificationPolicy,
)

from pipeline.agents.context import (
    ContextBuilder,
    ConversationContext,
)

from pipeline.agents.llm_runtime import (
    GeminiRuntime,
)

from pipeline.agents.schemas import (
    ConstraintSource,
    ExecutionPlan,
    ExtractedConstraint,
    Intent,
    ResearchDepth,
    ResponseModifier,
    RetrievalMode,
    RoutingLocation,
    RoutingRequest,
    StrictModel,
    SubTask,
    ToolName,
    TravelMode,
    WeatherMode,
    WeatherRequest,
)


logger = logging.getLogger(__name__)


# ============================================================
# INTERNAL LLM OUTPUT
# ============================================================


class PlannerConstraintDraft(StrictModel):
    """
    Constraint extracted from the current user message.

    ConstraintSource is intentionally absent: provider output must not
    decide whether a value came from conversation history or the current
    turn.
    """

    key: str = Field(
        min_length=1,
    )

    value: (
        str
        | int
        | float
        | bool
        | list[str]
        | None
    ) = None

    explicit: bool = True


class PlannerDraft(BaseModel):
    """
    Semantic interpretation trực tiếp từ Gemini.

    Đây CHƯA phải ExecutionPlan cuối.

    Gemini chịu trách nhiệm:
        - hiểu intent
        - tìm entity
        - hiểu nhu cầu của query
        - hiểu temporal expression
        - phát hiện capability cần dùng

    Python deterministic policy chịu trách nhiệm:
        - retrieval mode
        - research depth
        - fallback policy
        - coverage policy
        - tool routing
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    # --------------------------------------------------------
    # QUERY SEMANTICS
    # --------------------------------------------------------

    intent: Intent

    goal: str = Field(
        min_length=1,
    )

    entities: list[str] = Field(
        default_factory=list,
    )

    freshness_required: bool = False

    is_compound: bool = False

    # --------------------------------------------------------
    # CAPABILITY FLAGS
    # --------------------------------------------------------

    needs_travel_knowledge: bool = False

    needs_weather: bool = False

    needs_web_search: bool = False

    needs_routing: bool = False

    needs_budget: bool = False

    # --------------------------------------------------------
    # WEATHER SEMANTICS
    # --------------------------------------------------------

    weather_mode: WeatherMode = (
        WeatherMode.AUTO
    )

    weather_start_offset_days: int = 0

    weather_end_offset_days: int = 0

    weather_time_expression: (
        str | None
    ) = None

    # --------------------------------------------------------
    # OPTIONAL SEMANTIC INFO
    # --------------------------------------------------------

    semantic_subtasks: list[str] = Field(
        default_factory=list,
    )

    tool_arguments: dict[
        str,
        dict[str, Any],
    ] = Field(
        default_factory=dict,
    )

    constraints: list[
        PlannerConstraintDraft
    ] = Field(
        default_factory=list,
    )


# ============================================================
# PLANNER
# ============================================================


class TravelPlanner:
    """
    Gemini semantic planner
    +
    deterministic Python policy.

    Planner KHÔNG:
        - gọi RAG
        - gọi Tavily
        - gọi Weather API
        - gọi Routing API
        - tính budget
        - trả lời user

    Planner chỉ tạo ExecutionPlan.
    """

    def __init__(
        self,
        *,
        clarification_policy: (
            ClarificationPolicy | None
        ) = None,
        context_builder: (
            ContextBuilder | None
        ) = None,
        llm_runtime: GeminiRuntime | None = None,
    ) -> None:

        self.llm_runtime = (
            llm_runtime
            if llm_runtime is not None
            else GeminiRuntime()
        )

        self.clarification_policy = (
            clarification_policy
            if clarification_policy is not None
            else ClarificationPolicy(
                max_fields_per_turn=2
            )
        )

        self.context_builder = (
            context_builder
            if context_builder is not None
            else ContextBuilder()
        )

    # ========================================================
    # PROMPT
    # ========================================================

    def _build_prompt(
        self,
        query: str,
        context: (
            ConversationContext | None
        ) = None,
    ) -> str:

        conversation_context = (
            self.context_builder
            .planner_context_payload(
                context
            )
        )

        input_context = {
            "current_user_message": query,
            "conversation_context": (
                conversation_context
            ),
        }

        input_context_json = json.dumps(
            input_context,
            ensure_ascii=False,
            indent=2,
        )

        return f"""
Bạn là semantic planner của hệ thống
Vietnam Travel AI.

Nhiệm vụ:

PHÂN TÍCH câu hỏi của user.

KHÔNG trả lời user.
KHÔNG gọi tool.
KHÔNG giả lập kết quả tool.
KHÔNG quyết định corpus có dữ liệu hay không.
KHÔNG tự bịa địa điểm.


============================================================
INTENTS
============================================================

GENERAL

- chào hỏi
- giao tiếp thông thường
- câu hỏi không cần travel data


------------------------------------------------------------

FACTUAL_TRAVEL

Thông tin du lịch tương đối ổn định:

- địa danh
- điểm tham quan
- lịch sử
- văn hóa
- đặc điểm địa phương
- ẩm thực
- hoạt động du lịch


------------------------------------------------------------

RECOMMENDATION

- gợi ý địa điểm
- chọn nơi phù hợp nhu cầu
- đề xuất trải nghiệm
- nên đi đâu
- nơi nào phù hợp hơn theo tiêu chí


------------------------------------------------------------

COMPARISON

So sánh từ 2 địa điểm trở lên.

Ví dụ:

"Sa Pa và Đà Lạt khác nhau thế nào?"


------------------------------------------------------------

ITINERARY

- lập lịch trình
- lên kế hoạch chuyến đi
- chuyến đi nhiều ngày
- sắp xếp địa điểm


------------------------------------------------------------

WEATHER

- thời tiết
- mưa
- nắng
- nhiệt độ
- dự báo
- thời tiết hiện tại
- thời tiết những ngày gần đây


------------------------------------------------------------

ROUTING

- cách đi
- tuyến đường
- khoảng cách
- thời gian di chuyển
- đi từ A đến B
- phương tiện


------------------------------------------------------------

CURRENT_INFO

Use CURRENT_INFO when the user asks for information whose correct
value may change over time and should be checked from current external
sources.

Examples include:

- current ticket or admission prices
- current opening hours
- temporary closures
- current operating status
- current festivals or events
- recent changes to an attraction
- current rules or access conditions

CURRENT_INFO requires:

- freshness_required = true
- needs_web_search = true
- Web Search as the primary information source

Do not classify stable descriptive travel knowledge as CURRENT_INFO.

Examples:

"Datanla có gì?"
→ FACTUAL_TRAVEL

"Giá vé Datanla hiện tại bao nhiêu?"
→ CURRENT_INFO

"Datanla mở cửa lúc mấy giờ?"
→ CURRENT_INFO

"Đà Lạt có khí hậu như thế nào?"
→ FACTUAL_TRAVEL

"Festival Huế năm nay diễn ra khi nào?"
→ CURRENT_INFO


------------------------------------------------------------

BUDGET

- tính tổng chi phí
- ngân sách có đủ không
- chia ngân sách
- ước tính chi phí chuyến đi


------------------------------------------------------------

OUT_OF_SCOPE

Không thuộc travel và không phải
general conversation phù hợp.


============================================================
CAPABILITY FLAGS
============================================================

needs_travel_knowledge = true

khi cần knowledge du lịch tương đối ổn định:

- factual travel
- recommendation
- comparison
- itinerary


------------------------------------------------------------

needs_weather = true

khi user yêu cầu:

- current weather
- forecast
- historical recent weather
- temperature
- rain


------------------------------------------------------------

needs_web_search = true

CHỈ khi user trực tiếp cần
fresh/current information:

- giá hiện tại
- giờ mở cửa hiện tại
- closure
- event
- thông tin mới nhất

KHÔNG bật needs_web_search
chỉ vì lo internal RAG thiếu dữ liệu.

Knowledge retrieval layer tự xử lý
RAG fallback nếu corpus thiếu.


------------------------------------------------------------

needs_routing = true

khi cần:

- distance
- route
- travel duration
- cách đi
- phương tiện


------------------------------------------------------------

needs_budget = true

khi query cần:

- calculation
- budget assessment
- total cost


============================================================
WEATHER TEMPORAL PARSING
============================================================

Không chuyển relative date thành
calendar date YYYY-MM-DD.

Chỉ trả OFFSET so với ngày local hiện tại.

Ngày thực tế được WeatherTool resolve
deterministically ở runtime.


CURRENT / hiện tại / hôm nay:

weather_mode = CURRENT
weather_start_offset_days = 0
weather_end_offset_days = 0


"ngày mai":

weather_mode = FORECAST
weather_start_offset_days = 1
weather_end_offset_days = 1


"3 ngày nữa":

weather_mode = FORECAST
weather_start_offset_days = 3
weather_end_offset_days = 3


"5 ngày tới":

weather_mode = FORECAST_RANGE
weather_start_offset_days = 0
weather_end_offset_days = 5


"hôm qua":

weather_mode = RECENT_HISTORY
weather_start_offset_days = -1
weather_end_offset_days = -1


"3 ngày trước":

weather_mode = RECENT_HISTORY
weather_start_offset_days = -3
weather_end_offset_days = -3


"3 ngày gần đây":

weather_mode = RECENT_HISTORY_RANGE
weather_start_offset_days = -3
weather_end_offset_days = 0


QUAN TRỌNG:

Không tự clamp offset.

Ví dụ:

"15 ngày nữa Đà Lạt có mưa không?"

phải giữ:

weather_start_offset_days = 15
weather_end_offset_days = 15

WeatherTool sẽ tự kiểm tra
provider có hỗ trợ hay không.


weather_time_expression:

giữ lại text thời gian của user.

Ví dụ:

"ngày mai"
"3 ngày nữa"
"5 ngày tới"


============================================================
COMPOUND QUERY
============================================================

Một query có thể cần nhiều capability.

Ví dụ:

"Lập lịch Đà Nẵng 3 ngày tuần sau,
xem thời tiết và kiểm tra 5 triệu có đủ không"

Có thể:

intent = ITINERARY

needs_travel_knowledge = true
needs_weather = true
needs_budget = true

is_compound = true


============================================================
COMPARISON
============================================================

Ví dụ:

"Bà Nà và Măng Đen khác nhau như thế nào?"

Phải nhận ra:

intent = COMPARISON

entities = [
    "Bà Nà",
    "Măng Đen"
]

needs_travel_knowledge = true

Không bật needs_web_search chỉ vì
có thể corpus thiếu.

Knowledge layer sẽ tự:

RAG
→ coverage
→ web fallback nếu thiếu.


============================================================
ENTITY EXTRACTION
============================================================

Chỉ lấy explicit travel entity
được user thể hiện rõ.

Không hallucinate địa điểm.

Ví dụ:

"Ngày mai Đà Lạt có mưa không?"

entities = ["Đà Lạt"]


Ví dụ:

"Sa Pa và Đà Lạt khác nhau thế nào?"

entities = [
    "Sa Pa",
    "Đà Lạt"
]


============================================================
CONVERSATION CONTEXT RULES
============================================================

The current user message may be a follow-up to an earlier request.

Use conversation_context to resolve:

- omitted destinations
- omitted origins
- pronouns and references
- pending clarification answers
- previous trip constraints
- the active intent and goal

If pending_clarification exists and the current user message answers or
continues that request, interpret the message as part of the original
request.

Example:

Original request:
"Lập lịch Đà Lạt cho tôi."

Pending clarification:
trip_duration

Current message:
"3 ngày, đi với vợ, khoảng 6 triệu."

Resolved request remains an ITINERARY request for Đà Lạt.

The CURRENT message contributes:

trip_duration = "3 ngày"
travelers = 2
budget = 6000000

The previous destination "Đà Lạt" comes from conversation context.

IMPORTANT:

- intent, goal and entities must describe the resolved conversational
  request, not only the literal current sentence.
- constraints output must contain only constraints newly stated,
  changed, or explicitly reaffirmed in the CURRENT user message.
- Do not copy unchanged conversation constraints into constraints.
- A current explicit correction overrides old conversation context.
- If the user clearly changes topic, interpret the new request
  independently.


============================================================
CONSTRAINT EXTRACTION
============================================================

Extract useful constraints explicitly stated or clearly expressed
in the CURRENT user message.

Constraints use generic key/value pairs.

Prefer canonical keys when applicable:

destination
origin
trip_duration
travel_date
travel_date_range
travelers
budget
interests
activity_preferences
food_preferences
accommodation_preferences
transport_mode
pace
accessibility_needs
children
special_requirements

This list is guidance, not a closed vocabulary.
Use another clear snake_case key when needed.

Examples:

"Đi Đà Lạt 3 ngày"
→ destination = "Đà Lạt"
→ trip_duration = "3 ngày"

"Hai vợ chồng đi Đà Lạt khoảng 6 triệu"
→ destination = "Đà Lạt"
→ travelers = 2
→ budget = 6000000

"Tôi thích thiên nhiên, không thích check-in"
→ interests = ["thiên nhiên"]
→ activity_preferences may preserve the negative preference if useful.

"Ngày mai Đà Lạt có mưa không?"
→ destination = "Đà Lạt"
→ travel_date = "ngày mai"


TRANSPORT MODE NORMALIZATION

When the user explicitly specifies a transport mode,
normalize it to one of:

car
motorbike
bicycle
walking
taxi
bus
train
public_transit
air
ferry

Examples:

"đi ô tô" → transport_mode = "car"
"đi xe đạp" → transport_mode = "bicycle"
"đi taxi" → transport_mode = "taxi"
"đi xe máy" → transport_mode = "motorbike"
"đi bộ" → transport_mode = "walking"
"đi máy bay" → transport_mode = "air"

Do not invent a transport_mode if the user does not specify one.


ROUTING REQUESTS

For a routing request, identify:

- origin
- destination
- transport_mode if explicitly stated

Examples:

"Từ Ga Đà Lạt đến Thác Datanla bao xa?"
→ intent = ROUTING
→ origin = "Ga Đà Lạt"
→ destination = "Thác Datanla"

"Đi taxi từ chợ Đà Lạt đến Hồ Tuyền Lâm mất bao lâu?"
→ intent = ROUTING
→ origin = "Chợ Đà Lạt"
→ destination = "Hồ Tuyền Lâm"
→ transport_mode = "taxi"

"Chỉ đường đến Datanla"
→ intent = ROUTING
→ destination = "Datanla"
→ origin is unknown

RULES:

- Extract only information supported by the current user message.
- Do not invent defaults.
- Do not emit missing or unknown constraints.
- Do not guess budget, number of travelers, duration, dates,
  preferences, origin, or destination.
- Set explicit=true when the user directly states the value.
- Preserve useful user constraints even if they are not required by
  the immediate tool call.
- If the user supplies several constraints in one sentence, extract
  all of them.
- A follow-up message may contain more information than the field that
  was previously asked; extract every useful constraint present.


============================================================
SEMANTIC SUBTASKS
============================================================

Có thể mô tả các nhu cầu độc lập.

Ví dụ:

"Lập lịch Đà Nẵng 3 ngày,
xem thời tiết và kiểm tra 5 triệu có đủ không"

semantic_subtasks:

[
    "Tìm thông tin du lịch Đà Nẵng",
    "Kiểm tra thời tiết Đà Nẵng",
    "Đánh giá ngân sách 5 triệu"
]


============================================================
TOOL ARGUMENT HINTS
============================================================

tool_arguments có thể chứa
semantic arguments chuẩn bị trước.

Key hợp lệ:

travel_knowledge
weather
web_search
routing
budget


Ví dụ WEATHER:

"Ngày mai Đà Lạt có mưa không?"

tool_arguments:

{{
    "weather": {{
        "location": "Đà Lạt"
    }}
}}


Ví dụ CURRENT INFO:

"Giá vé Bà Nà hiện tại bao nhiêu?"

tool_arguments:

{{
    "web_search": {{
        "entity": "Bà Nà"
    }}
}}


Không invent:

- price
- distance
- coordinates
- route
- weather result
- budget values user không cung cấp


============================================================
IMPORTANT RULES
============================================================

- Không trả lời user.
- Không hallucinate entity.
- Không giả lập tool result.
- Không thêm web search cho static travel knowledge.
- Weather luôn freshness-sensitive.
- CURRENT_INFO luôn freshness-sensitive.
- Compound query phải giữ mọi capability cần thiết.
- Comparison phải giữ đủ explicit entities.
- Relative date chỉ convert thành offset.
- Không tính ngày calendar.


============================================================
INPUT
============================================================

{input_context_json}
""".strip()

    # ========================================================
    # GEMINI STRUCTURED OUTPUT
    # ========================================================

    def _analyze_with_gemini(
        self,
        query: str,
        *,
        context: (
            ConversationContext | None
        ) = None,
        ) -> PlannerDraft:

        response = (
            self.llm_runtime.generate_content(
                model=settings.gemini_model,

                contents=self._build_prompt(
                    query,
                    context=context,
                ),

                config=types.GenerateContentConfig(
                    temperature=0.1,

                    response_mime_type=(
                        "application/json"
                    ),

                    response_json_schema=(
                        PlannerDraft
                        .model_json_schema()
                    ),
                ),
            )
        )

        response_text = response.text

        if not response_text:

            raise RuntimeError(
                "Gemini không trả PlannerDraft."
            )

        try:

            return (
                PlannerDraft
                .model_validate_json(
                    response_text
                )
            )

        except ValidationError as exc:

            raise RuntimeError(
                "Planner structured output "
                "không hợp lệ."
            ) from exc

    # ========================================================
    # NORMALIZATION
    # ========================================================

    @staticmethod
    def _unique_strings(
        values: list[str],
    ) -> list[str]:

        output: list[str] = []

        seen: set[str] = set()

        for value in values:

            value = str(
                value
            ).strip()

            if not value:
                continue

            key = value.casefold()

            if key in seen:
                continue

            seen.add(key)

            output.append(
                value
            )

        return output

    @staticmethod
    def _fold_text(value: str) -> str:
        normalized = unicodedata.normalize("NFD", value.casefold())
        folded = "".join(
            character
            for character in normalized
            if unicodedata.category(character) != "Mn"
        )
        return folded.replace("đ", "d")

    @classmethod
    def _response_modifier(cls, query: str) -> ResponseModifier | None:
        """Recognize only clear, standalone refinement requests."""

        folded = re.sub(r"[^a-z0-9\s]", " ", cls._fold_text(query))
        folded = re.sub(r"\s+", " ", folded).strip()
        patterns = {
            ResponseModifier.EXPAND: (
                r"^(?:dai|chi tiet) hon$",
                r"^noi (?:ky|ro) hon$",
                r"^giai thich ro hon$",
            ),
            ResponseModifier.CONDENSE: (
                r"^ngan hon$",
                r"^ngan thoi$",
                r"^rut gon(?: lai)?$",
                r"^tom tat(?: thoi)?$",
            ),
            ResponseModifier.ADD_OPTIONS: (
                r"^them nua$",
                r"^them (?:vai )?(?:cho|noi|dia diem)(?: nua)?$",
                r"^con (?:cho|noi|dia diem) nao (?:nua|khac)(?: khong)?$",
                r"^goi y them(?: di)?$",
            ),
        }
        for modifier, candidates in patterns.items():
            if any(re.fullmatch(pattern, folded) for pattern in candidates):
                return modifier
        return None

    @classmethod
    def _is_booking_transaction(cls, query: str) -> bool:
        folded = cls._fold_text(query)
        patterns = (
            r"\bdat\s+(?:giup\s+)?(?:toi\s+)?(?:phong|khach san|tour|ve)\b",
            r"\bbook\s+(?:giup\s+)?(?:toi\s+)?",
            r"\bmua\s+ve\s+.*\bgiup\s+(?:toi|minh)\b",
            r"\bthanh\s+toan\s+.*\bgiup\s+(?:toi|minh)\b",
        )
        return any(re.search(pattern, folded) for pattern in patterns)

    @classmethod
    def _requires_fresh_web(cls, query: str) -> bool:
        folded = cls._fold_text(query)
        freshness_phrases = (
            "hien tai",
            "hien nay",
            "hom nay",
            "tuan nay",
            "moi nhat",
            "dang hot",
            "nam nay",
        )
        return any(phrase in folded for phrase in freshness_phrases)

    @classmethod
    def _strengthen_specific_entities(
        cls,
        query: str,
        entities: list[str],
    ) -> list[str]:
        prefixes = ("ga", "san bay", "ben xe")
        folded_query = cls._fold_text(query)
        strengthened: list[str] = []

        for entity in entities:
            folded_entity = cls._fold_text(entity)
            replacement = entity
            for prefix in prefixes:
                phrase = f"{prefix} {folded_entity}"
                if phrase in folded_query and not folded_entity.startswith(
                    f"{prefix} "
                ):
                    start = folded_query.index(phrase)
                    replacement = query[start : start + len(phrase)]
                    break
            strengthened.append(replacement)

        return cls._unique_strings(strengthened)

    def _apply_deterministic_semantics(
        self,
        *,
        query: str,
        draft: PlannerDraft,
        context: ConversationContext | None,
    ) -> PlannerDraft:
        if self._is_booking_transaction(query):
            return draft.model_copy(
                update={
                    "intent": Intent.OUT_OF_SCOPE,
                    "goal": (
                        "Giải thích giới hạn không thể thực hiện đặt chỗ, "
                        "mua vé hoặc thanh toán thay người dùng."
                    ),
                    "freshness_required": False,
                    "is_compound": False,
                    "needs_travel_knowledge": False,
                    "needs_weather": False,
                    "needs_web_search": False,
                    "needs_routing": False,
                    "needs_budget": False,
                    "semantic_subtasks": [],
                    "tool_arguments": {},
                }
            )

        pending = context.pending_clarification if context is not None else None
        update: dict[str, Any] = {}

        modifier = self._response_modifier(query)
        active_task = context.active_task if context is not None else None
        if modifier is not None and pending is None and active_task is not None:
            active_intent = active_task.intent
            update.update(
                {
                    "intent": active_intent,
                    "goal": active_task.goal,
                    "entities": list(active_task.entities),
                    "freshness_required": False,
                    "is_compound": False,
                    "needs_travel_knowledge": active_intent in {
                        Intent.FACTUAL_TRAVEL,
                        Intent.RECOMMENDATION,
                        Intent.COMPARISON,
                        Intent.ITINERARY,
                    },
                    "needs_weather": active_intent == Intent.WEATHER,
                    "needs_web_search": active_intent == Intent.CURRENT_INFO,
                    "needs_routing": active_intent == Intent.ROUTING,
                    "needs_budget": active_intent == Intent.BUDGET,
                    "semantic_subtasks": [],
                    "tool_arguments": {},
                    "constraints": [],
                }
            )
            logger.info(
                "Response modifier inherited active task",
                extra={
                    "intent": active_intent.value,
                    "response_modifier": modifier.value,
                    "active_context_inherited": True,
                },
            )

        if pending is not None and pending.original_intent is not None:
            update["intent"] = pending.original_intent
            if pending.original_goal:
                update["goal"] = pending.original_goal
            update["entities"] = self._unique_strings(
                [*pending.original_entities, *draft.entities]
            )
            logger.info(
                "Clarification resumed original intent",
                extra={"intent": pending.original_intent.value},
            )

        effective_intent = update.get("intent", draft.intent)
        if (
            effective_intent
            in {Intent.FACTUAL_TRAVEL, Intent.RECOMMENDATION, Intent.CURRENT_INFO}
            and self._requires_fresh_web(query)
        ):
            update.update(
                {
                    "intent": Intent.CURRENT_INFO,
                    "freshness_required": True,
                    "needs_web_search": True,
                    "needs_travel_knowledge": False,
                }
            )

        entities = update.get("entities", draft.entities)
        update["entities"] = self._strengthen_specific_entities(query, entities)
        return draft.model_copy(update=update)

    @classmethod
    def _resolved_query(
        cls,
        query: str,
        context: ConversationContext | None,
    ) -> str:
        if context is None:
            return query
        if context.pending_clarification is not None:
            return (
                f"{context.pending_clarification.original_query}\n"
                f"Thông tin bổ sung: {query}"
            )
        modifier = cls._response_modifier(query)
        if modifier is not None and context.active_task is not None:
            return (
                f"Tác vụ đang tiếp tục: {context.active_task.query}\n"
                f"Mục tiêu: {context.active_task.goal}\n"
                f"Yêu cầu điều chỉnh: {query}"
            )
        return query

    @staticmethod
    def _build_constraints(
        draft: PlannerDraft,
    ) -> list[ExtractedConstraint]:
        """
        Convert provider-owned drafts into domain constraints.

        The source is assigned here so the LLM cannot claim that a
        value came from conversation memory or a clarification turn.
        """

        constraints: list[
            ExtractedConstraint
        ] = []

        seen: set[
            tuple[str, str]
        ] = set()

        for item in draft.constraints:

            key = (
                item.key
                .strip()
                .lower()
                .replace("-", "_")
                .replace(" ", "_")
            )

            if not key:
                continue

            value = item.value

            if value is None:
                continue

            if isinstance(
                value,
                str,
            ):

                value = value.strip()

                if not value:
                    continue

            elif isinstance(
                value,
                list,
            ):

                value = (
                    TravelPlanner
                    ._unique_strings(
                        value
                    )
                )

                if not value:
                    continue

            fingerprint = (
                key,
                repr(value),
            )

            if fingerprint in seen:
                continue

            seen.add(
                fingerprint
            )

            constraints.append(
                ExtractedConstraint(
                    key=key,
                    value=value,
                    source=(
                        ConstraintSource
                        .CURRENT_MESSAGE
                    ),
                    explicit=(
                        item.explicit
                    ),
                )
            )

        return constraints

    @staticmethod
    def _constraint_value(
        constraints: list[ExtractedConstraint],
        key: str,
    ) -> Any:
        for item in reversed(constraints):
            if item.key == key:
                return item.value

        return None

    @staticmethod
    def _resolve_travel_mode(
        constraints: list[ExtractedConstraint],
    ) -> TravelMode:
        raw = TravelPlanner._constraint_value(
            constraints,
            "transport_mode",
        )

        if not isinstance(raw, str):
            return TravelMode.CAR

        try:
            return TravelMode(
                raw.strip().lower()
            )
        except ValueError:
            return TravelMode.CAR

    def _build_routing_task(
        self,
        *,
        constraints: list[ExtractedConstraint],
        task_id: str,
    ) -> SubTask | None:
        origin = self._constraint_value(
            constraints,
            "origin",
        )
        destination = self._constraint_value(
            constraints,
            "destination",
        )

        if (
            not isinstance(origin, str)
            or not origin.strip()
        ):
            return None

        if (
            not isinstance(destination, str)
            or not destination.strip()
        ):
            return None

        request = RoutingRequest(
            origin=RoutingLocation(
                query=origin,
            ),
            destination=RoutingLocation(
                query=destination,
            ),
            mode=self._resolve_travel_mode(
                constraints
            ),
        )

        return self._task(
            task_id=task_id,
            description=(
                "Tìm tuyến đường từ "
                f"{origin.strip()} đến "
                f"{destination.strip()}"
            ),
            tool=ToolName.ROUTING,
            arguments=request.model_dump(
                mode="json"
            ),
        )

    def _build_current_info_task(
        self,
        *,
        query: str,
        entities: list[str],
        task_id: str,
    ) -> SubTask:
        search_query = query.strip()
        clean_entities = self._unique_strings(
            entities
        )

        if clean_entities:
            entity_text = " ".join(clean_entities)

            if (
                entity_text
                and entity_text.casefold()
                not in search_query.casefold()
            ):
                search_query = (
                    f"{entity_text}: {search_query}"
                )

        arguments: dict[str, Any] = {
            "query": search_query,
        }

        if len(clean_entities) == 1:
            arguments["entity"] = clean_entities[0]

        return self._task(
            task_id=task_id,
            description="Tìm thông tin fresh/current",
            tool=ToolName.WEB_SEARCH,
            arguments=arguments,
        )

    def _apply_clarification_policy(
        self,
        plan: ExecutionPlan,
    ) -> ExecutionPlan:

        decision = (
            self.clarification_policy
            .evaluate(
                intent=plan.intent,
                constraints=(
                    plan.constraints
                ),
                entities=plan.entities,
                subtasks=plan.subtasks,
                ambiguity_fields=None,
            )
        )

        if not decision.needs_clarification:
            return plan

        return plan.model_copy(
            update={
                "clarification": (
                    decision.clarification
                ),
                "subtasks": [],
                "retrieval_mode": (
                    RetrievalMode.DIRECT
                ),
                "fallback_to_web": False,
                "require_all_entities": False,
                "coverage_entities": [],
            }
        )

    # ========================================================
    # TASK FACTORY
    # ========================================================

    @staticmethod
    def _task(
        *,
        task_id: str,
        description: str,
        tool: ToolName,
        arguments: dict[str, Any],
        depends_on: list[str] | None = None,
    ) -> SubTask:

        return SubTask(
            task_id=task_id,

            description=description,

            tool=tool,

            arguments=arguments,

            depends_on=(
                depends_on
                or []
            ),

            required=True,
        )

    # ========================================================
    # DETERMINISTIC EXECUTION POLICY
    # ========================================================

    def _build_execution_plan(
        self,
        *,
        query: str,
        draft: PlannerDraft,
        context: (
            ConversationContext | None
        ) = None,
    ) -> ExecutionPlan:

        original_query = query
        modifier = self._response_modifier(original_query)
        query = self._resolved_query(original_query, context)

        entities = (
            self._unique_strings(
                draft.entities
            )
        )

        current_constraints = (
            self._build_constraints(
                draft
            )
        )

        constraints = (
            self.context_builder
            .prepare_constraints_for_turn(
                context=context,
                current_constraints=(
                    current_constraints
                ),
                intent=draft.intent,
            )
        )

        if (
            context is None
            or context.active_task is None
            or context.pending_clarification is not None
        ):
            modifier = None

        if not entities:
            for constraint in constraints:
                if constraint.key == "destination" and isinstance(constraint.value, str):
                    entities = [constraint.value]
                    break

        subtasks: list[
            SubTask
        ] = []

        pure_current_info = (
            draft.intent == Intent.CURRENT_INFO
            and not draft.is_compound
        )

        task_number = 1

        # ----------------------------------------------------
        # Stable task IDs
        # ----------------------------------------------------

        def next_id() -> str:

            nonlocal task_number

            value = (
                f"task_{task_number}"
            )

            task_number += 1

            return value

        # ====================================================
        # DIRECT QUERY
        # ====================================================

        if draft.intent in {
            Intent.GENERAL,
            Intent.OUT_OF_SCOPE,
        }:

            plan = ExecutionPlan(
                intent=draft.intent,

                goal=draft.goal,

                entities=entities,

                freshness_required=False,

                is_compound=False,

                retrieval_mode=(
                    RetrievalMode.DIRECT
                ),

                research_depth=(
                    ResearchDepth.BASIC
                ),

                subtasks=[],

                fallback_to_web=False,

                require_all_entities=False,

                coverage_entities=[],

                constraints=constraints,
            )

            return (
                self
                ._apply_clarification_policy(
                    plan
                )
            )

        # ====================================================
        # TRAVEL KNOWLEDGE
        # ====================================================

        needs_rag = (
            draft.needs_travel_knowledge
            or draft.intent
            in {
                Intent.FACTUAL_TRAVEL,
                Intent.RECOMMENDATION,
                Intent.COMPARISON,
                Intent.ITINERARY,
            }
        )

        if pure_current_info:
            needs_rag = False

        if needs_rag:

            rag_arguments = dict(
                draft.tool_arguments.get(
                    "travel_knowledge",
                    {},
                )
            )

            # Deterministic override:
            # không tin LLM cho các field policy.
            rag_arguments[
                "query"
            ] = query

            rag_arguments[
                "entities"
            ] = entities

            rag_arguments[
                "require_all_entities"
            ] = bool(
                entities
            )

            subtasks.append(
                self._task(
                    task_id=next_id(),

                    description=(
                        "Tìm knowledge du lịch "
                        "liên quan tới câu hỏi"
                    ),

                    tool=ToolName.RAG,

                    arguments=(
                        rag_arguments
                    ),
                )
            )

        # ====================================================
        # WEATHER
        # ====================================================

        needs_weather = (
            draft.needs_weather
            or draft.intent
            == Intent.WEATHER
        )

        if pure_current_info:
            needs_weather = False

        if needs_weather:

            raw_weather_args = dict(
                draft.tool_arguments.get(
                    "weather",
                    {},
                )
            )

            raw_location = (
                raw_weather_args.get(
                    "location"
                )
            )

            if raw_location:

                location = str(
                    raw_location
                ).strip()

            elif entities:

                location = (
                    entities[0]
                )

            else:

                location = ""

            # ------------------------------------------------
            # Có location:
            # validate bằng WeatherRequest.
            # ------------------------------------------------

            if location:

                weather_request = (
                    WeatherRequest(
                        location=location,

                        mode=(
                            draft.weather_mode
                        ),

                        start_offset_days=(
                            draft
                            .weather_start_offset_days
                        ),

                        end_offset_days=(
                            draft
                            .weather_end_offset_days
                        ),

                        time_expression=(
                            draft
                            .weather_time_expression
                        ),

                        original_query=query,
                    )
                )

                weather_arguments = (
                    weather_request
                    .model_dump(
                        mode="json"
                    )
                )

            # ------------------------------------------------
            # Không có location:
            #
            # vẫn tạo task.
            # WeatherTool/Validator sau này báo
            # WEATHER_LOCATION_MISSING.
            #
            # Không để Planner crash.
            # ------------------------------------------------

            else:

                weather_arguments = {
                    "location": "",

                    "mode": (
                        draft
                        .weather_mode
                        .value
                    ),

                    "start_offset_days": (
                        draft
                        .weather_start_offset_days
                    ),

                    "end_offset_days": (
                        draft
                        .weather_end_offset_days
                    ),

                    "time_expression": (
                        draft
                        .weather_time_expression
                    ),

                    "original_query": query,
                }

            subtasks.append(
                self._task(
                    task_id=next_id(),

                    description=(
                        "Lấy dữ liệu thời tiết"
                        + (
                            f" cho {location}"
                            if location
                            else ""
                        )
                    ),

                    tool=ToolName.WEATHER,

                    arguments=(
                        weather_arguments
                    ),
                )
            )

        # ====================================================
        # CURRENT / FRESH WEB DATA
        # ====================================================

        needs_web = (
            draft.needs_web_search
            or draft.intent
            == Intent.CURRENT_INFO
        )

        if needs_web:
            subtasks.append(
                self._build_current_info_task(
                    task_id=next_id(),
                    query=query,
                    entities=entities,
                )
            )

        # ====================================================
        # ROUTING
        # ====================================================

        needs_routing = (
            draft.needs_routing
            or draft.intent
            == Intent.ROUTING
        )

        if pure_current_info:
            needs_routing = False

        if needs_routing:

            routing_task = self._build_routing_task(
                constraints=constraints,
                task_id=next_id(),
            )

            if routing_task is not None:
                subtasks.append(routing_task)

        # ====================================================
        # BUDGET
        # ====================================================

        needs_budget = (
            draft.needs_budget
            or draft.intent
            == Intent.BUDGET
        )

        if pure_current_info:
            needs_budget = False

        if needs_budget:

            budget_arguments = dict(
                draft.tool_arguments.get(
                    "budget",
                    {},
                )
            )

            budget_arguments[
                "query"
            ] = query

            budget_arguments[
                "entities"
            ] = entities

            subtasks.append(
                self._task(
                    task_id=next_id(),

                    description=(
                        "Tính toán hoặc "
                        "đánh giá ngân sách"
                    ),

                    tool=(
                        ToolName.BUDGET
                    ),

                    arguments=(
                        budget_arguments
                    ),
                )
            )

        # Pure response refinements can reuse the bounded, selected
        # support persisted with the active task. ADD_OPTIONS intentionally
        # keeps retrieval because it asks for new grounded material.
        active_task = context.active_task if context is not None else None
        if modifier == ResponseModifier.CONDENSE:
            subtasks = []
        elif modifier == ResponseModifier.EXPAND and active_task is not None:
            available_tools = {
                item.tool
                for item in active_task.tool_observations
            }
            has_research = bool(active_task.research_evidence)
            subtasks = [
                task
                for task in subtasks
                if not (
                    task.tool in {ToolName.RAG, ToolName.WEB_SEARCH}
                    and has_research
                )
                and task.tool not in available_tools
            ]

        # ====================================================
        # USED TOOLS
        # ====================================================

        used_tools = {
            task.tool
            for task in subtasks
        }

        # ====================================================
        # RETRIEVAL MODE POLICY
        # ====================================================

        if len(used_tools) > 1:

            retrieval_mode = (
                RetrievalMode.MIXED
            )

        elif (
            ToolName.RAG
            in used_tools
        ):

            retrieval_mode = (
                RetrievalMode.RAG_FIRST
            )

        elif (
            ToolName.WEB_SEARCH
            in used_tools
        ):

            retrieval_mode = (
                RetrievalMode.WEB_FIRST
            )

        elif used_tools:

            retrieval_mode = (
                RetrievalMode.TOOL_ONLY
            )

        else:

            retrieval_mode = (
                RetrievalMode.DIRECT
            )

        # ====================================================
        # RESEARCH DEPTH POLICY
        # ====================================================

        """
        BASIC:

            Internal RAG là backbone.

            Web chỉ dùng:
                - direct CURRENT_INFO
                - hoặc RAG fallback khi thiếu.


        ENRICHED:

            Complex travel task cần thêm
            external evidence dù RAG đã cover.

            Tool executor/evidence layer sau này
            sẽ thực hiện:

                RAG
                +
                web enrichment
                ↓
                merge
                ↓
                rerank
        """

        if draft.intent in {
            Intent.COMPARISON,
            Intent.RECOMMENDATION,
            Intent.ITINERARY,
        }:

            research_depth = (
                ResearchDepth.ENRICHED
            )

        else:

            research_depth = (
                ResearchDepth.BASIC
            )

        if modifier == ResponseModifier.EXPAND:
            research_depth = ResearchDepth.DEEP
        elif modifier == ResponseModifier.CONDENSE:
            research_depth = ResearchDepth.BASIC

        # ====================================================
        # COVERAGE POLICY
        # ====================================================

        require_all_entities = (
            ToolName.RAG
            in used_tools
            and bool(
                entities
            )
        )

        coverage_entities = (
            entities
            if require_all_entities
            else []
        )

        # ====================================================
        # WEB FALLBACK POLICY
        # ====================================================

        """
        True nghĩa là knowledge tool được phép:

            RAG
              ↓
            coverage thiếu
              ↓
            web fallback

        KHÔNG có nghĩa web được gọi ngay.
        """

        fallback_to_web = (
            ToolName.RAG
            in used_tools
        )

        # ====================================================
        # FRESHNESS POLICY
        # ====================================================

        freshness_required = (
            draft.intent
            == Intent.CURRENT_INFO
            or draft.freshness_required
            or needs_weather
            or needs_web
            or needs_routing
        )

        # ====================================================
        # COMPOUND POLICY
        # ====================================================

        is_compound = (
            draft.is_compound

            or len(subtasks) > 1

            or (
                draft.intent
                == Intent.COMPARISON

                and len(
                    entities
                ) >= 2
            )
        )

        # ====================================================
        # FINAL EXECUTION PLAN
        # ====================================================

        plan = ExecutionPlan(
            intent=draft.intent,

            goal=draft.goal,

            entities=entities,

            freshness_required=(
                freshness_required
            ),

            is_compound=(
                is_compound
            ),

            retrieval_mode=(
                retrieval_mode
            ),

            research_depth=(
                research_depth
            ),

            response_modifier=modifier,

            subtasks=subtasks,

            fallback_to_web=(
                fallback_to_web
            ),

            require_all_entities=(
                require_all_entities
            ),

            coverage_entities=(
                coverage_entities
            ),

            constraints=constraints,
        )

        return (
            self
            ._apply_clarification_policy(
                plan
            )
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def plan(
        self,
        query: str,
        *,
        context: (
            ConversationContext | None
        ) = None,
    ) -> ExecutionPlan:

        query = query.strip()

        if not query:

            raise ValueError(
                "Query không được rỗng."
            )

        draft = (
            self._analyze_with_gemini(
                query,
                context=context,
            )
        )

        draft = self._apply_deterministic_semantics(
            query=query,
            draft=draft,
            context=context,
        )

        return (
            self._build_execution_plan(
                query=query,
                draft=draft,
                context=context,
            )
        )


# ============================================================
# CLI
# ============================================================


def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Vietnam Travel Agent Planner"
        )
    )

    parser.add_argument(
        "query",
        nargs="+",
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    query = " ".join(
        args.query
    ).strip()

    planner = TravelPlanner()

    plan = planner.plan(
        query
    )

    print()

    print("=" * 90)
    print("AGENT PLANNER")
    print("=" * 90)

    print(
        f"Query              : "
        f"{query}"
    )

    print(
        f"Intent             : "
        f"{plan.intent.value}"
    )

    print(
        f"Goal               : "
        f"{plan.goal}"
    )

    print(
        f"Entities           : "
        f"{plan.entities}"
    )

    print(
        f"Freshness required : "
        f"{plan.freshness_required}"
    )

    print(
        f"Compound           : "
        f"{plan.is_compound}"
    )

    print(
        f"Retrieval mode     : "
        f"{plan.retrieval_mode.value}"
    )

    print(
        f"Research depth     : "
        f"{plan.research_depth.value}"
    )

    print(
        f"Fallback to web    : "
        f"{plan.fallback_to_web}"
    )

    print(
        f"Require all entity : "
        f"{plan.require_all_entities}"
    )

    print(
        f"Coverage entities  : "
        f"{plan.coverage_entities}"
    )

    print()
    print("SUBTASKS")

    if not plan.subtasks:

        print("  -")

    for task in plan.subtasks:

        arguments_json = (
            json.dumps(
                task.arguments,

                ensure_ascii=False,

                indent=2,
            )
        )

        print()

        print(
            f"  [{task.task_id}]"
        )

        print(
            f"  Description : "
            f"{task.description}"
        )

        print(
            f"  Tool        : "
            f"{task.tool.value}"
        )

        print(
            f"  Required    : "
            f"{task.required}"
        )

        print(
            f"  Depends on  : "
            f"{task.depends_on}"
        )

        print(
            f"  Arguments   : "
            f"{arguments_json}"
        )


if __name__ == "__main__":
    main()
