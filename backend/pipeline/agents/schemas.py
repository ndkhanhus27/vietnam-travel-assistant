from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


# ============================================================
# BASE MODEL
# ============================================================


class StrictModel(BaseModel):
    """
    Base schema dùng chung cho agent system.

    extra="forbid":
        Nếu Gemini/tool trả field lạ,
        validation sẽ fail thay vì silently ignore.
    """

    model_config = ConfigDict(
        extra="forbid",
    )


# ============================================================
# INTENTS
# ============================================================


class Intent(str, Enum):
    """
    High-level intent của user query.

    Không đồng nghĩa mỗi intent có một agent riêng.
    Intent chỉ phục vụ planning/routing.
    """

    GENERAL = "GENERAL"

    FACTUAL_TRAVEL = "FACTUAL_TRAVEL"
    RECOMMENDATION = "RECOMMENDATION"
    COMPARISON = "COMPARISON"
    ITINERARY = "ITINERARY"

    WEATHER = "WEATHER"
    ROUTING = "ROUTING"
    CURRENT_INFO = "CURRENT_INFO"
    BUDGET = "BUDGET"

    OUT_OF_SCOPE = "OUT_OF_SCOPE"


# ============================================================
# RETRIEVAL / EXECUTION MODES
# ============================================================


class RetrievalMode(str, Enum):
    """
    Cách xử lý knowledge của query.

    DIRECT:
        Không cần retrieval/tool.

    RAG_FIRST:
        Internal RAG trước.
        Nếu thiếu evidence có thể web fallback.

    WEB_FIRST:
        Query freshness-sensitive.
        Web trước.

    TOOL_ONLY:
        Dùng specialized tool.
        Ví dụ weather/routing.

    MIXED:
        Compound query cần nhiều source/tool.
    """

    DIRECT = "DIRECT"
    RAG_FIRST = "RAG_FIRST"
    WEB_FIRST = "WEB_FIRST"
    TOOL_ONLY = "TOOL_ONLY"
    MIXED = "MIXED"


# ============================================================
# AVAILABLE TOOLS
# ============================================================


class ToolName(str, Enum):
    """
    Canonical tool names.

    Sau này Python tools hoặc MCP tools
    đều giữ cùng tên này.
    """

    RAG = "search_travel_knowledge"

    WEB_SEARCH = "web_search"

    WEATHER = "weather"

    MAP_LOCATION = "map_location"

    ROUTING = "routing"

    BUDGET = "budget_calculator"
    
# ============================================================
# WEATHER
# ============================================================


class WeatherMode(str, Enum):
    """
    Kiểu weather request.

    CURRENT
        Thời tiết hiện tại.

    FORECAST
        Một ngày trong tương lai.

    FORECAST_RANGE
        Một khoảng ngày tương lai.

    RECENT_HISTORY
        Một ngày gần đây trong quá khứ.

    RECENT_HISTORY_RANGE
        Một khoảng ngày gần đây.

    AUTO
        Planner chưa xác định rõ;
        WeatherTool sẽ resolve từ query.
    """

    CURRENT = "CURRENT"

    FORECAST = "FORECAST"

    FORECAST_RANGE = "FORECAST_RANGE"

    RECENT_HISTORY = "RECENT_HISTORY"

    RECENT_HISTORY_RANGE = (
        "RECENT_HISTORY_RANGE"
    )

    AUTO = "AUTO"
    
class WeatherRequest(StrictModel):
    """
    Contract dành riêng cho WeatherTool.

    Planner chỉ mô tả thời gian user muốn hỏi.

    WeatherTool sau này chịu trách nhiệm:
    - resolve ngày thực tế
    - timezone
    - kiểm tra provider horizon
    - gọi API

    offset:
        0   = hôm nay
        1   = ngày mai
        3   = 3 ngày nữa
        -1  = hôm qua
        -3  = 3 ngày trước
    """

    location: str = Field(
        min_length=1,
    )

    mode: WeatherMode = (
        WeatherMode.AUTO
    )

    start_offset_days: int = 0

    end_offset_days: int = 0

    time_expression: str | None = None

    original_query: str = Field(
        min_length=1,
    )


# ============================================================
# TASK STATUS
# ============================================================


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


# ============================================================
# SUBTASK
# ============================================================


class SubTask(StrictModel):
    """
    Một unit công việc do Planner tạo.

    Ví dụ:

        task_id = "weather_dalat"

        description =
            "Kiểm tra thời tiết Đà Lạt ngày mai"

        tool = WEATHER

        arguments = {
            "location": "Đà Lạt",
            "date_expression": "ngày mai"
        }

    depends_on dùng để tạo DAG nhỏ.
    """

    task_id: str = Field(
        min_length=1,
    )

    description: str = Field(
        min_length=1,
    )

    tool: ToolName

    arguments: dict[str, Any] = Field(
        default_factory=dict,
    )

    depends_on: list[str] = Field(
        default_factory=list,
    )

    required: bool = True


# ============================================================
# EXECUTION PLAN
# ============================================================


class ExecutionPlan(StrictModel):
    """
    Structured output chính của Planner.

    Planner Gemini sẽ sinh object này.
    """

    intent: Intent

    goal: str = Field(
        min_length=1,
    )

    entities: list[str] = Field(
        default_factory=list,
    )

    freshness_required: bool = False

    is_compound: bool = False

    retrieval_mode: RetrievalMode

    subtasks: list[SubTask] = Field(
        default_factory=list,
    )

    # --------------------------------------------------------
    # Adaptive RAG policy
    # --------------------------------------------------------

    fallback_to_web: bool = False

    require_all_entities: bool = False

    coverage_entities: list[str] = Field(
        default_factory=list,
    )


# ============================================================
# TOOL OBSERVATION
# ============================================================

class ToolObservation(StrictModel):
    """
    Output chuẩn hóa của mọi tool.

    Tool có thể là:
    - RAG
    - Tavily
    - Weather
    - Routing
    - Budget

    LangGraph chỉ làm việc với contract này.
    """

    task_id: str

    tool: ToolName

    status: TaskStatus

    data: dict[str, Any] = Field(
        default_factory=dict,
    )

    evidence: list[EvidenceItem] = Field(
        default_factory=list,
    )

    coverage: CoverageResult | None = None

    error: str | None = None

    source_count: int = 0


# ============================================================
# UNIFIED EVIDENCE
# ============================================================


class EvidenceSource(str, Enum):
    RAG = "rag"
    WEB = "web"
    WEATHER = "weather"
    MAP = "map"
    ROUTING = "routing"
    CALCULATION = "calculation"


class EvidenceItem(StrictModel):
    """
    Evidence chuẩn hóa.

    Đây là lớp trung gian rất quan trọng.

    RAG chunk và Tavily result sau này đều convert
    về EvidenceItem trước khi đưa cho Gemini.
    """

    evidence_id: str

    source_type: EvidenceSource

    title: str

    content: str

    url: str | None = None

    entity: str | None = None

    score: float | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


# ============================================================
# COVERAGE
# ============================================================


class CoverageResult(StrictModel):
    """
    Kết quả kiểm tra evidence coverage.

    Example:

        required_entities:
            ["Bà Nà", "Măng Đen"]

        covered_entities:
            ["Bà Nà"]

        missing_entities:
            ["Măng Đen"]

        sufficient:
            False
    """

    required_entities: list[str] = Field(
        default_factory=list,
    )

    covered_entities: list[str] = Field(
        default_factory=list,
    )

    missing_entities: list[str] = Field(
        default_factory=list,
    )

    sufficient: bool
    



# ============================================================
# VALIDATION
# ============================================================


class ValidationIssue(StrictModel):
    """
    Một lỗi do deterministic Validator phát hiện.
    """

    code: str

    message: str

    task_id: str | None = None

    recoverable: bool = True


class ValidationResult(StrictModel):
    """
    Output của Validator Node.
    """

    valid: bool

    issues: list[ValidationIssue] = Field(
        default_factory=list,
    )


# ============================================================
# FINAL RESPONSE
# ============================================================


class Citation(StrictModel):
    """
    Citation mà frontend có thể render thành source card.
    """

    citation_id: str

    evidence_id: str

    title: str

    url: str | None = None

    source_type: EvidenceSource


class AgentResponse(StrictModel):
    """
    Output cuối của agent service.

    Sau này FastAPI /chat có thể trả cấu trúc này.
    """

    answer: str

    citations: list[Citation] = Field(
        default_factory=list,
    )

    intent: Intent

    used_tools: list[ToolName] = Field(
        default_factory=list,
    )

    needs_followup: bool = False
    
