from __future__ import annotations

import argparse
import json
from typing import Any

from google import genai
from google.genai import types
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from app.core.config import settings

from pipeline.agents.schemas import (
    ExecutionPlan,
    Intent,
    RetrievalMode,
    SubTask,
    ToolName,
    WeatherMode,
    WeatherRequest,
)

# ============================================================
# INTERNAL LLM OUTPUT
# ============================================================


class PlannerDraft(BaseModel):
    """
    Output semantic trực tiếp từ Gemini.

    Không dùng class này ngoài planner.py.

    Các policy quan trọng như:
    - retrieval mode
    - fallback
    - coverage
    - required tool

    sẽ được Python quyết định sau.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    intent: Intent

    goal: str = Field(
        min_length=1,
    )

    entities: list[str] = Field(
        default_factory=list,
    )

    freshness_required: bool = False

    is_compound: bool = False

    needs_travel_knowledge: bool = False

    needs_weather: bool = False

    weather_mode: WeatherMode = (
        WeatherMode.AUTO
    )

    weather_start_offset_days: int = 0

    weather_end_offset_days: int = 0

    weather_time_expression: str | None = None
    needs_web_search: bool = False

    needs_routing: bool = False

    needs_budget: bool = False

    semantic_subtasks: list[str] = Field(
        default_factory=list,
    )

    tool_arguments: dict[
        str,
        dict[str, Any],
    ] = Field(
        default_factory=dict,
    )


# ============================================================
# PLANNER
# ============================================================


class TravelPlanner:
    """
    Gemini semantic planner
    +
    deterministic routing policy.

    Gemini:
        hiểu user query.

    Python:
        quyết định execution policy.

    Planner KHÔNG:
        - gọi RAG
        - gọi Tavily
        - gọi Weather API
        - trả lời user
    """

    def __init__(self) -> None:

        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY chưa được cấu hình."
            )

        self.client = genai.Client(
            api_key=settings.gemini_api_key
        )

    # ========================================================
    # PROMPT
    # ========================================================

    @staticmethod
    def _build_prompt(
        query: str,
    ) -> str:

        return f"""
Bạn là Planner của hệ thống Vietnam Travel AI.

Nhiệm vụ của bạn:

PHÂN TÍCH câu hỏi của user.

KHÔNG trả lời câu hỏi.

KHÔNG giả lập kết quả tool.

KHÔNG tự quyết định corpus có dữ liệu hay không.


============================================================
INTENTS
============================================================

GENERAL

- chào hỏi
- giao tiếp thông thường
- không yêu cầu dữ liệu du lịch cụ thể


FACTUAL_TRAVEL

- hỏi địa danh
- điểm tham quan
- lịch sử
- văn hóa
- đặc điểm du lịch
- thông tin tương đối ổn định


RECOMMENDATION

- gợi ý địa điểm
- chọn nơi phù hợp sở thích
- đề xuất trải nghiệm


COMPARISON

- so sánh từ hai địa điểm trở lên

Ví dụ:

"Sa Pa và Đà Lạt khác nhau như thế nào?"


ITINERARY

- lịch trình
- kế hoạch chuyến đi
- chuyến đi nhiều ngày


WEATHER

- mưa
- nắng
- nhiệt độ
- thời tiết
- dự báo


ROUTING

- cách đi
- quãng đường
- thời gian di chuyển
- tuyến đường
- đi từ A đến B


CURRENT_INFO

Thông tin có thể thay đổi theo thời gian:

- giá vé hiện tại
- giờ mở cửa hiện tại
- tình trạng đóng/mở
- sự kiện đang diễn ra
- thông tin hôm nay
- thông tin mới nhất


BUDGET

- tính ngân sách
- tổng chi phí
- ngân sách có đủ hay không


OUT_OF_SCOPE

- không thuộc travel
- không phải general conversation phù hợp


============================================================
SEMANTIC FLAGS
============================================================

needs_travel_knowledge = true

khi cần kiến thức du lịch tương đối ổn định:

- địa danh
- attractions
- văn hóa
- recommendation
- comparison
- itinerary


needs_weather = true

khi user yêu cầu dữ liệu weather.


needs_web_search = true

CHỈ khi user trực tiếp yêu cầu
fresh/current information như:

- giá hiện tại
- mở cửa hiện tại
- closure
- event
- mới nhất

KHÔNG bật web_search chỉ vì lo corpus thiếu.
RAG tool sẽ tự fallback web khi corpus thiếu.


needs_routing = true

khi cần:
- route
- distance
- duration
- phương tiện/cách di chuyển


needs_budget = true

khi cần tính toán ngân sách.


============================================================
COMPOUND QUERY
============================================================

Một query có thể cần nhiều capability.

Ví dụ:

"Lập lịch Đà Nẵng 3 ngày tuần sau,
xem thời tiết và 5 triệu có đủ không"

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

Phải:

intent = COMPARISON

entities = [
    "Bà Nà",
    "Măng Đen"
]

needs_travel_knowledge = true

Không cần needs_web_search=true.

Knowledge tool tự thực hiện:

RAG first
→ kiểm tra từng entity
→ chỉ web fallback entity thiếu.


============================================================
ENTITY EXTRACTION
============================================================

Chỉ lấy entity được user thể hiện rõ.

Không hallucinate entity.

Ví dụ:

"Ngày mai Đà Lạt có mưa không?"

entities = ["Đà Lạt"]


============================================================
SEMANTIC SUBTASKS
============================================================

semantic_subtasks mô tả các nhu cầu độc lập.

Ví dụ:

"Lập lịch Đà Nẵng 3 ngày,
xem thời tiết và kiểm tra 5 triệu có đủ không"

semantic_subtasks:

[
    "Tìm thông tin và điểm tham quan ở Đà Nẵng",
    "Kiểm tra thời tiết Đà Nẵng",
    "Kiểm tra ngân sách 5 triệu"
]


============================================================
TOOL ARGUMENTS
============================================================

Có thể chuẩn bị argument semantic cho từng capability.

Key hợp lệ:

travel_knowledge
weather
web_search
routing
budget

Ví dụ:

"Ngày mai Đà Lạt có mưa không?"

tool_arguments:

{{
    "weather": {{
        "location": "Đà Lạt",
        "query": "Ngày mai Đà Lạt có mưa không?"
    }}
}}

Ví dụ:

"Giá vé Bà Nà hiện tại bao nhiêu?"

tool_arguments:

{{
    "web_search": {{
        "query": "Giá vé Bà Nà hiện tại bao nhiêu?",
        "entity": "Bà Nà"
    }}
}}

Không invent giá trị mà user không cung cấp.


============================================================
IMPORTANT
============================================================

- Không trả lời user.
- Không hallucinate địa điểm.
- Không invent tool result.
- Không thêm web_search cho static travel knowledge.
- Weather luôn là fresh data.
- Current info luôn freshness_required=true.
- Compound query phải giữ tất cả capability cần thiết.


USER QUERY:

{query}
""".strip()

    # ========================================================
    # GEMINI
    # ========================================================

    def _analyze_with_gemini(
        self,
        query: str,
    ) -> PlannerDraft:

        response = (
            self.client.models.generate_content(
                model=settings.gemini_model,
                contents=self._build_prompt(
                    query
                ),
                config=types.GenerateContentConfig(
                    temperature=0,

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

        if not response.text:
            raise RuntimeError(
                "Gemini không trả PlannerDraft."
            )

        try:

            payload = json.loads(
                response.text
            )

            return (
                PlannerDraft
                .model_validate(
                    payload
                )
            )

        except (
            json.JSONDecodeError,
            ValidationError,
        ) as exc:

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

            value = value.strip()

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
    # DETERMINISTIC POLICY
    # ========================================================

    def _build_execution_plan(
        self,
        *,
        query: str,
        draft: PlannerDraft,
    ) -> ExecutionPlan:

        entities = (
            self._unique_strings(
                draft.entities
            )
        )

        subtasks: list[
            SubTask
        ] = []

        task_number = 1

        # ----------------------------------------------------
        # Helper for stable IDs:
        # task_1, task_2, ...
        # ----------------------------------------------------

        def next_id() -> str:

            nonlocal task_number

            value = (
                f"task_{task_number}"
            )

            task_number += 1

            return value

        # ====================================================
        # GENERAL / OUT OF SCOPE
        # ====================================================

        if draft.intent in {
            Intent.GENERAL,
            Intent.OUT_OF_SCOPE,
        }:

            return ExecutionPlan(
                intent=draft.intent,

                goal=draft.goal,

                entities=entities,

                freshness_required=False,

                is_compound=False,

                retrieval_mode=(
                    RetrievalMode.DIRECT
                ),

                subtasks=[],

                fallback_to_web=False,

                require_all_entities=False,

                coverage_entities=[],
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

        if needs_rag:

            rag_arguments = dict(
                draft.tool_arguments.get(
                    "travel_knowledge",
                    {},
                )
            )

            rag_arguments.update(
                {
                    "query": query,

                    "entities": (
                        entities
                    ),

                    "require_all_entities": (
                        bool(entities)
                    ),
                }
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

        if needs_weather:
            location = (
                entities[0]
                if entities
                else ""
            )

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

            subtasks.append(
                self._task(
                    task_id=next_id(),

                    description=(
                        "Lấy dữ liệu thời tiết "
                        f"cho {location}"
                    ),

                    tool=ToolName.WEATHER,

                    arguments=(
                        weather_request
                        .model_dump(
                            mode="json"
                        )
                    ),
                )
            )

        # ====================================================
        # CURRENT WEB DATA
        # ====================================================

        needs_web = (
            draft.needs_web_search
            or draft.intent
            == Intent.CURRENT_INFO
        )

        if needs_web:

            web_arguments = dict(
                draft.tool_arguments.get(
                    "web_search",
                    {},
                )
            )

            web_arguments[
                "query"
            ] = query

            if (
                "entity"
                not in web_arguments
                and len(entities) == 1
            ):
                web_arguments[
                    "entity"
                ] = entities[0]

            subtasks.append(
                self._task(
                    task_id=next_id(),

                    description=(
                        "Tìm thông tin "
                        "fresh/current"
                    ),

                    tool=(
                        ToolName.WEB_SEARCH
                    ),

                    arguments=(
                        web_arguments
                    ),
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

        if needs_routing:

            routing_arguments = dict(
                draft.tool_arguments.get(
                    "routing",
                    {},
                )
            )

            routing_arguments[
                "query"
            ] = query

            routing_arguments[
                "entities"
            ] = entities

            subtasks.append(
                self._task(
                    task_id=next_id(),

                    description=(
                        "Tìm tuyến đường và "
                        "thông tin di chuyển"
                    ),

                    tool=(
                        ToolName.ROUTING
                    ),

                    arguments=(
                        routing_arguments
                    ),
                )
            )

        # ====================================================
        # BUDGET
        # ====================================================

        needs_budget = (
            draft.needs_budget
            or draft.intent
            == Intent.BUDGET
        )

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

        # ====================================================
        # RETRIEVAL MODE
        # ====================================================

        used_tools = {
            item.tool
            for item in subtasks
        }

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
        # COVERAGE POLICY
        # ====================================================

        require_all_entities = (
            ToolName.RAG
            in used_tools
            and bool(entities)
        )

        coverage_entities = (
            entities
            if require_all_entities
            else []
        )

        # ====================================================
        # WEB FALLBACK POLICY
        # ====================================================

        fallback_to_web = (
            ToolName.RAG
            in used_tools
        )

        # ====================================================
        # FRESHNESS POLICY
        # ====================================================

        freshness_required = (
            draft.freshness_required
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
                and len(entities) >= 2
            )
        )

        return ExecutionPlan(
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
        )

    # ========================================================
    # PUBLIC
    # ========================================================

    def plan(
        self,
        query: str,
    ) -> ExecutionPlan:

        query = query.strip()

        if not query:
            raise ValueError(
                "Query không được rỗng."
            )

        draft = (
            self._analyze_with_gemini(
                query
            )
        )

        return (
            self._build_execution_plan(
                query=query,
                draft=draft,
            )
        )


# ============================================================
# CLI FOR STEP-BY-STEP TESTING
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

    print("=" * 80)
    print("AGENT PLANNER")
    print("=" * 80)

    print(
        f"Query              : {query}"
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

        arguments_json = json.dumps(
            task.arguments,
            ensure_ascii=False,
            indent=2,
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
