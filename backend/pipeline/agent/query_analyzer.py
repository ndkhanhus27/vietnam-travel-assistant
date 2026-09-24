from __future__ import annotations

import argparse
import json
from enum import Enum

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings


# ============================================================
# ENUMS
# ============================================================


class QueryIntent(str, Enum):
    GENERAL = "GENERAL"

    FACTUAL_TRAVEL = "FACTUAL_TRAVEL"
    RECOMMENDATION = "RECOMMENDATION"
    COMPARISON = "COMPARISON"
    ITINERARY = "ITINERARY"

    WEATHER = "WEATHER"
    ROUTING = "ROUTING"
    CURRENT_INFO = "CURRENT_INFO"

    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class ToolName(str, Enum):
    RAG = "rag"
    WEATHER = "weather"
    ROUTING = "routing"
    WEB = "web"
    BUDGET = "budget"


class RetrievalMode(str, Enum):
    """
    DIRECT:
        Không retrieval.

    RAG_FIRST:
        Search internal corpus trước.
        Nếu evidence không đủ thì có thể fallback.

    WEB_FIRST:
        Dùng nguồn fresh/current trước.

    TOOL_ONLY:
        Dùng specialized tool như weather/routing.
    """

    DIRECT = "DIRECT"
    RAG_FIRST = "RAG_FIRST"
    WEB_FIRST = "WEB_FIRST"
    TOOL_ONLY = "TOOL_ONLY"


# ============================================================
# RAW GEMINI OUTPUT
# ============================================================


class RawQueryAnalysis(BaseModel):
    """
    Output trực tiếp từ Gemini.

    Chỉ chứa semantic interpretation.

    Routing policy quan trọng sẽ được code Python
    chuẩn hóa ở bước sau, không để LLM tự quyết định hoàn toàn.
    """

    intent: QueryIntent

    freshness_required: bool

    is_compound: bool

    entities: list[str] = Field(
        default_factory=list,
        description=(
            "Các địa danh hoặc thực thể du lịch "
            "xuất hiện rõ ràng trong câu hỏi."
        ),
    )

    sub_queries: list[str] = Field(
        default_factory=list,
        description=(
            "Các câu hỏi con độc lập cần xử lý."
        ),
    )

    suggested_tools: list[ToolName] = Field(
        default_factory=list,
        description=(
            "Các tool có khả năng cần thiết "
            "để xử lý câu hỏi."
        ),
    )


# ============================================================
# FINAL QUERY PLAN
# ============================================================


class QueryAnalysis(BaseModel):
    """
    Query plan sau khi áp deterministic routing policy.
    """

    intent: QueryIntent

    freshness_required: bool

    is_compound: bool

    entities: list[str]

    sub_queries: list[str]

    # --------------------------------------------------------
    # Retrieval plan
    # --------------------------------------------------------

    retrieval_mode: RetrievalMode

    required_tools: list[ToolName]

    # --------------------------------------------------------
    # RAG fallback policy
    # --------------------------------------------------------

    fallback_to_web: bool

    require_all_entities: bool

    coverage_entities: list[str]

    retrieval_queries: list[str]


# ============================================================
# QUERY ANALYZER
# ============================================================


class QueryAnalyzer:
    """
    Analyze user query and create an execution plan.

    Gemini:
        semantic interpretation

    Python deterministic policy:
        routing
        fallback rules
        entity coverage rules

    QueryAnalyzer KHÔNG kiểm tra corpus.

    Việc corpus có evidence hay không sẽ được kiểm tra
    sau retrieval bởi workflow / evidence gate.
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
Bạn là Query Analyzer cho hệ thống Vietnam Travel AI.

NHIỆM VỤ:

Phân tích query của người dùng.

KHÔNG trả lời câu hỏi.

Chỉ trả về structured metadata để hệ thống
có thể lập kế hoạch retrieval/tool execution.


============================================================
INTENTS
============================================================

GENERAL

Dùng cho:
- chào hỏi
- trò chuyện thông thường
- hội thoại không yêu cầu thông tin du lịch cụ thể


FACTUAL_TRAVEL

Dùng cho:
- địa điểm có gì
- điểm tham quan
- lịch sử
- văn hóa
- đặc điểm địa danh
- thông tin du lịch tương đối ổn định

Ví dụ:

"Bà Nà có gì tham quan?"


RECOMMENDATION

Dùng khi người dùng cần:
- gợi ý địa điểm
- chọn nơi phù hợp sở thích
- tìm nơi phù hợp điều kiện

Ví dụ:

"Tôi thích núi và khí hậu mát thì nên đi đâu?"


COMPARISON

Dùng khi cần so sánh hai hoặc nhiều địa điểm.

Ví dụ:

"Sa Pa và Đà Lạt khác nhau như thế nào?"

Khi COMPARISON:

- entities phải chứa tất cả địa điểm rõ ràng.
- nên tạo sub-query riêng cho từng địa điểm.
- không được chỉ phân tích một bên.


ITINERARY

Dùng cho:
- lập lịch trình
- kế hoạch chuyến đi
- chuyến đi nhiều ngày
- nhiều hoạt động cần phối hợp


WEATHER

Dùng cho:
- thời tiết
- nhiệt độ
- mưa
- nắng
- dự báo

WEATHER luôn:

freshness_required = true


ROUTING

Dùng cho:
- đường đi
- khoảng cách
- thời gian di chuyển
- phương tiện
- cách đi từ A tới B


CURRENT_INFO

Thông tin thay đổi theo thời gian:

- giá vé hiện tại
- giờ mở cửa hiện tại
- đóng cửa / mở cửa
- sự kiện hiện tại
- tình trạng hoạt động
- thông tin mới nhất
- hôm nay
- hiện tại
- lịch hoạt động hiện tại

CURRENT_INFO luôn:

freshness_required = true


OUT_OF_SCOPE

Query không liên quan tới:
- du lịch
- travel planning
- hoặc general conversation phù hợp.


============================================================
AVAILABLE TOOLS
============================================================

rag

Dùng cho knowledge tương đối ổn định:

- địa điểm
- điểm tham quan
- lịch sử
- văn hóa
- recommendation
- comparison
- itinerary knowledge


weather

Dùng cho:
- thời tiết
- forecast
- temperature
- rain


routing

Dùng cho:
- route
- khoảng cách
- thời gian di chuyển


web

Dùng cho:
- thông tin mới nhất
- giá hiện tại
- giờ mở cửa
- closures
- events
- dữ liệu freshness-sensitive

LƯU Ý:

Không cần thêm web chỉ vì nghi ngờ RAG có thể thiếu dữ liệu.

Hệ thống có deterministic web fallback riêng.

Nếu query là static travel knowledge,
ưu tiên suggested_tools = ["rag"].


budget

Dùng cho:
- cộng/trừ chi phí
- kiểm tra ngân sách
- tính tổng ngân sách


============================================================
QUERY DECOMPOSITION
============================================================

Nếu query chứa nhiều nhiệm vụ độc lập:

is_compound = true

và tách thành sub_queries.


Ví dụ:

"Đi Đà Nẵng 3 ngày tuần sau,
thời tiết thế nào và 5 triệu có đủ không?"

sub_queries:

1. Lập lịch trình Đà Nẵng 3 ngày
2. Kiểm tra thời tiết Đà Nẵng tuần sau
3. Kiểm tra ngân sách 5 triệu


============================================================
COMPARISON DECOMPOSITION
============================================================

Đặc biệt với COMPARISON:

"Sa Pa và Đà Lạt khác nhau như thế nào?"

Không được chỉ tạo:

"Sa Pa và Đà Lạt khác nhau thế nào?"

Hãy tạo retrieval-oriented subqueries cho từng nơi.

Ví dụ:

1. Thông tin du lịch Sa Pa liên quan đến việc so sánh
2. Thông tin du lịch Đà Lạt liên quan đến việc so sánh

entities:

[
    "Sa Pa",
    "Đà Lạt"
]


============================================================
ENTITY EXTRACTION
============================================================

Chỉ lấy entity xuất hiện hoặc được thể hiện rõ trong query.

Không hallucinate entity.


Ví dụ:

"Sa Pa và Đà Lạt khác nhau thế nào?"

entities:

[
    "Sa Pa",
    "Đà Lạt"
]


============================================================
IMPORTANT
============================================================

Không quyết định rằng corpus chắc chắn có dữ liệu.

Bạn KHÔNG biết corpus hiện tại chứa những gì.

Corpus coverage sẽ được kiểm tra sau retrieval.

Chỉ thực hiện semantic analysis của query.


USER QUERY:

{query}
""".strip()

    # ========================================================
    # GEMINI ANALYSIS
    # ========================================================

    def _analyze_with_gemini(
        self,
        query: str,
    ) -> RawQueryAnalysis:

        prompt = self._build_prompt(
            query
        )

        response = (
            self.client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type=(
                        "application/json"
                    ),
                    response_json_schema=(
                        RawQueryAnalysis
                        .model_json_schema()
                    ),
                ),
            )
        )

        if not response.text:
            raise RuntimeError(
                "Gemini không trả về QueryAnalysis."
            )

        try:
            raw = json.loads(
                response.text
            )

            return (
                RawQueryAnalysis
                .model_validate(raw)
            )

        except (
            json.JSONDecodeError,
            ValidationError,
        ) as exc:

            raise RuntimeError(
                "Structured output của "
                "Query Analyzer không hợp lệ."
            ) from exc

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _unique_entities(
        entities: list[str],
    ) -> list[str]:

        output: list[str] = []

        seen: set[str] = set()

        for entity in entities:

            entity = entity.strip()

            if not entity:
                continue

            key = entity.casefold()

            if key in seen:
                continue

            seen.add(key)

            output.append(entity)

        return output

    @staticmethod
    def _unique_tools(
        tools: list[ToolName],
    ) -> list[ToolName]:

        output: list[ToolName] = []

        seen: set[ToolName] = set()

        for tool in tools:

            if tool in seen:
                continue

            seen.add(tool)

            output.append(tool)

        return output

    # ========================================================
    # RETRIEVAL QUERY BUILDING
    # ========================================================

    @staticmethod
    def _build_retrieval_queries(
        *,
        query: str,
        intent: QueryIntent,
        entities: list[str],
        sub_queries: list[str],
    ) -> list[str]:

        # ----------------------------------------------------
        # Comparison is special.
        #
        # Mỗi entity phải được retrieve độc lập.
        # Điều này tránh trường hợp một địa điểm dominate
        # toàn bộ candidate list.
        # ----------------------------------------------------

        if (
            intent == QueryIntent.COMPARISON
            and len(entities) >= 2
        ):

            return [
                (
                    f"{entity}: thông tin du lịch "
                    f"cần thiết để trả lời câu hỏi "
                    f"'{query}'"
                )
                for entity in entities
            ]

        # ----------------------------------------------------
        # Compound query.
        # ----------------------------------------------------

        if sub_queries:
            return [
                item.strip()
                for item in sub_queries
                if item.strip()
            ]

        return [query]

    # ========================================================
    # DETERMINISTIC ROUTING POLICY
    # ========================================================

    @staticmethod
    def _apply_policy(
        *,
        query: str,
        raw: RawQueryAnalysis,
    ) -> QueryAnalysis:

        intent = raw.intent

        entities = (
            QueryAnalyzer
            ._unique_entities(
                raw.entities
            )
        )

        sub_queries = [
            item.strip()
            for item in raw.sub_queries
            if item.strip()
        ]

        # ====================================================
        # GENERAL
        # ====================================================

        if intent == QueryIntent.GENERAL:

            return QueryAnalysis(
                intent=intent,

                freshness_required=False,

                is_compound=(
                    raw.is_compound
                ),

                entities=entities,

                sub_queries=sub_queries,

                retrieval_mode=(
                    RetrievalMode.DIRECT
                ),

                required_tools=[],

                fallback_to_web=False,

                require_all_entities=False,

                coverage_entities=[],

                retrieval_queries=[],
            )

        # ====================================================
        # OUT OF SCOPE
        # ====================================================

        if (
            intent
            == QueryIntent.OUT_OF_SCOPE
        ):

            return QueryAnalysis(
                intent=intent,

                freshness_required=False,

                is_compound=(
                    raw.is_compound
                ),

                entities=entities,

                sub_queries=sub_queries,

                retrieval_mode=(
                    RetrievalMode.DIRECT
                ),

                required_tools=[],

                fallback_to_web=False,

                require_all_entities=False,

                coverage_entities=[],

                retrieval_queries=[],
            )

        # ====================================================
        # WEATHER
        # ====================================================

        if intent == QueryIntent.WEATHER:

            return QueryAnalysis(
                intent=intent,

                freshness_required=True,

                is_compound=(
                    raw.is_compound
                ),

                entities=entities,

                sub_queries=sub_queries,

                retrieval_mode=(
                    RetrievalMode.TOOL_ONLY
                ),

                required_tools=[
                    ToolName.WEATHER
                ],

                fallback_to_web=False,

                require_all_entities=False,

                coverage_entities=[],

                retrieval_queries=[],
            )

        # ====================================================
        # ROUTING
        # ====================================================

        if intent == QueryIntent.ROUTING:

            return QueryAnalysis(
                intent=intent,

                freshness_required=True,

                is_compound=(
                    raw.is_compound
                ),

                entities=entities,

                sub_queries=sub_queries,

                retrieval_mode=(
                    RetrievalMode.TOOL_ONLY
                ),

                required_tools=[
                    ToolName.ROUTING
                ],

                fallback_to_web=False,

                require_all_entities=False,

                coverage_entities=[],

                retrieval_queries=[],
            )

        # ====================================================
        # CURRENT INFORMATION
        # ====================================================

        if (
            intent
            == QueryIntent.CURRENT_INFO
        ):

            return QueryAnalysis(
                intent=intent,

                freshness_required=True,

                is_compound=(
                    raw.is_compound
                ),

                entities=entities,

                sub_queries=sub_queries,

                retrieval_mode=(
                    RetrievalMode.WEB_FIRST
                ),

                required_tools=[
                    ToolName.WEB
                ],

                fallback_to_web=False,

                require_all_entities=False,

                coverage_entities=[],

                retrieval_queries=[],
            )

        # ====================================================
        # STATIC / SEMANTIC TRAVEL KNOWLEDGE
        # ====================================================

        retrieval_queries = (
            QueryAnalyzer
            ._build_retrieval_queries(
                query=query,
                intent=intent,
                entities=entities,
                sub_queries=sub_queries,
            )
        )

        tools = list(
            raw.suggested_tools
        )

        # Static travel always gets RAG first.
        if ToolName.RAG not in tools:
            tools.insert(
                0,
                ToolName.RAG,
            )

        # Do NOT force web here.
        #
        # Web will be triggered only when evidence gate
        # determines that internal corpus is insufficient.

        tools = (
            QueryAnalyzer
            ._unique_tools(tools)
        )

        # ----------------------------------------------------
        # Comparison:
        #
        # evidence must cover EVERY explicit entity.
        #
        # Sa Pa + Đà Lạt:
        # having only Sa Pa evidence is NOT enough.
        # ----------------------------------------------------
        
        # Nếu user nêu rõ địa điểm thì RAG phải thực sự
        # có evidence cho địa điểm đó.
        #
        # Ví dụ:
        # "Măng Đen có gì chơi?"
        # entities = ["Măng Đen"]
        #
        # Nếu corpus không có Măng Đen, không được dùng
        # một document địa điểm khác để trả lời.

        coverage_entities = entities

        require_all_entities = bool(
            coverage_entities
        )

        return QueryAnalysis(
            intent=intent,

            freshness_required=(
                raw.freshness_required
            ),

            is_compound=(
                raw.is_compound
                or (
                    intent
                    == QueryIntent.COMPARISON
                    and len(entities) >= 2
                )
            ),

            entities=entities,

            sub_queries=sub_queries,

            retrieval_mode=(
                RetrievalMode.RAG_FIRST
            ),

            required_tools=tools,

            # ------------------------------------------------
            # IMPORTANT:
            #
            # factual / recommendation / comparison /
            # itinerary may fall back to web when:
            #
            # - corpus has no relevant evidence
            # - reranker evidence too weak
            # - entity is missing
            # - comparison does not cover every entity
            # ------------------------------------------------

            fallback_to_web=True,

            require_all_entities=(
                require_all_entities
            ),

            coverage_entities=(
                coverage_entities
            ),

            retrieval_queries=(
                retrieval_queries
            ),
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def analyze(
        self,
        query: str,
    ) -> QueryAnalysis:

        query = query.strip()

        if not query:
            raise ValueError(
                "Query không được rỗng."
            )

        raw = (
            self._analyze_with_gemini(
                query
            )
        )

        return self._apply_policy(
            query=query,
            raw=raw,
        )


# ============================================================
# CLI
# ============================================================


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Vietnam Travel "
            "Query Analyzer"
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

    analyzer = QueryAnalyzer()

    result = analyzer.analyze(
        query
    )

    print()

    print("=" * 80)
    print("QUERY ANALYSIS")
    print("=" * 80)

    print(
        f"Query                : "
        f"{query}"
    )

    print(
        f"Intent               : "
        f"{result.intent.value}"
    )

    print(
        f"Freshness required   : "
        f"{result.freshness_required}"
    )

    print(
        f"Compound             : "
        f"{result.is_compound}"
    )

    print(
        f"Entities             : "
        f"{result.entities}"
    )

    print(
        f"Retrieval mode       : "
        f"{result.retrieval_mode.value}"
    )

    print(
        f"Required tools       : "
        f"{[tool.value for tool in result.required_tools]}"
    )

    print(
        f"Fallback to web      : "
        f"{result.fallback_to_web}"
    )

    print(
        f"Require all entities : "
        f"{result.require_all_entities}"
    )

    print(
        f"Coverage entities    : "
        f"{result.coverage_entities}"
    )

    print()

    print("Sub queries:")

    if not result.sub_queries:
        print("  -")

    else:
        for index, sub_query in enumerate(
            result.sub_queries,
            start=1,
        ):
            print(
                f"  {index}. "
                f"{sub_query}"
            )

    print()

    print("Retrieval queries:")

    if not result.retrieval_queries:
        print("  -")

    else:
        for index, retrieval_query in enumerate(
            result.retrieval_queries,
            start=1,
        ):
            print(
                f"  {index}. "
                f"{retrieval_query}"
            )


if __name__ == "__main__":
    main()
