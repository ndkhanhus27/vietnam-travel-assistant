from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
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
# RESEARCH DEPTH
# ============================================================


class ResearchDepth(str, Enum):
    """
    Mức độ research cho travel knowledge.

    BASIC
        Internal RAG là nguồn chính.
        Web chỉ fallback nếu corpus thiếu.

    ENRICHED
        Internal RAG + external web enrichment
        ngay cả khi RAG đã cover đủ.

    DEEP
        Reserved cho deep research sau này.
    """

    BASIC = "BASIC"
    ENRICHED = "ENRICHED"
    DEEP = "DEEP"


class ResponseModifier(str, Enum):
    """Internal operation applied to the active conversational task."""

    EXPAND = "EXPAND"
    CONDENSE = "CONDENSE"
    ADD_OPTIONS = "ADD_OPTIONS"

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

    DISTANCE_MATRIX = "distance_matrix"

    BUDGET = "budget_calculator"


# ============================================================
# MAP LOCATION
# ============================================================


class MapLocationMode(str, Enum):
    FORWARD = "forward"
    REVERSE = "reverse"


class GeoPoint(StrictModel):
    lat: float = Field(
        ge=-90.0,
        le=90.0,
    )

    lon: float = Field(
        ge=-180.0,
        le=180.0,
    )


class MapLocationRequest(StrictModel):
    mode: MapLocationMode = (
        MapLocationMode.FORWARD
    )

    query: str | None = None

    point: GeoPoint | None = None

    limit: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    @model_validator(mode="after")
    def validate_mode_input(self) -> MapLocationRequest:
        has_query = bool(
            self.query
            and self.query.strip()
        )
        has_point = self.point is not None

        if self.mode == MapLocationMode.FORWARD:
            if not has_query or has_point:
                raise ValueError(
                    "Forward map location requests require "
                    "a non-empty query and no point."
                )

        if self.mode == MapLocationMode.REVERSE:
            if not has_point or self.query is not None:
                raise ValueError(
                    "Reverse map location requests require "
                    "a point and no query."
                )

        return self


class MapLocationCandidate(StrictModel):
    name: str | None = None

    formatted_address: str | None = None

    place_id: str | None = None

    point: GeoPoint


class MapLocationResult(StrictModel):
    mode: MapLocationMode

    query: str | None = None

    point: GeoPoint | None = None

    candidates: list[MapLocationCandidate] = Field(
        default_factory=list,
    )


# ============================================================
# ROUTING
# ============================================================


class TravelMode(str, Enum):
    """
    Domain-level transport mode.

    Không đồng nghĩa với vehicle token của Goong.
    """

    CAR = "car"
    MOTORBIKE = "motorbike"
    BICYCLE = "bicycle"
    WALKING = "walking"
    TAXI = "taxi"
    BUS = "bus"
    TRAIN = "train"
    PUBLIC_TRANSIT = "public_transit"
    AIR = "air"
    FERRY = "ferry"


class RoutingLocation(StrictModel):
    """
    Một đầu route được mô tả bằng query hoặc point, không phải cả hai.
    """

    query: str | None = None
    point: GeoPoint | None = None

    @model_validator(mode="after")
    def validate_location_input(self) -> RoutingLocation:
        has_query = bool(
            self.query
            and self.query.strip()
        )
        has_point = self.point is not None

        if has_query == has_point:
            raise ValueError(
                "RoutingLocation requires exactly one of query or point."
            )

        if self.query is not None:
            self.query = self.query.strip()

        return self


class RoutingRequest(StrictModel):
    origin: RoutingLocation
    destination: RoutingLocation
    mode: TravelMode = TravelMode.CAR
    alternatives: bool = False


class ResolvedRouteLocation(StrictModel):
    query: str | None = None
    name: str | None = None
    formatted_address: str | None = None
    place_id: str | None = None
    point: GeoPoint


class RouteStep(StrictModel):
    instruction: str | None = None
    maneuver: str | None = None
    distance_meters: float = Field(
        default=0.0,
        ge=0.0,
    )
    duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )
    start_point: GeoPoint | None = None
    end_point: GeoPoint | None = None
    polyline: str | None = None


class RouteLeg(StrictModel):
    distance_meters: float = Field(
        default=0.0,
        ge=0.0,
    )
    duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )
    start_address: str | None = None
    end_address: str | None = None
    start_point: GeoPoint | None = None
    end_point: GeoPoint | None = None
    steps: list[RouteStep] = Field(
        default_factory=list,
    )


class RouteAlternative(StrictModel):
    distance_meters: float = Field(
        default=0.0,
        ge=0.0,
    )
    duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )
    summary: str | None = None
    polyline: str | None = None
    legs: list[RouteLeg] = Field(
        default_factory=list,
    )


class RoutingResult(StrictModel):
    requested_mode: TravelMode
    provider_vehicle: str
    origin: ResolvedRouteLocation
    destination: ResolvedRouteLocation
    routes: list[RouteAlternative] = Field(
        default_factory=list,
    )


# ============================================================
# DISTANCE MATRIX
# ============================================================


class DistanceMatrixRequest(StrictModel):
    """
    N origins x M destinations.

    The 10-location cap on each axis is an application guard,
    not a statement about the provider limit.
    """

    origins: list[RoutingLocation] = Field(
        min_length=1,
        max_length=10,
    )
    destinations: list[RoutingLocation] = Field(
        min_length=1,
        max_length=10,
    )
    mode: TravelMode = TravelMode.CAR


class DistanceMatrixElement(StrictModel):
    """One origin[i] -> destination[j] matrix cell."""

    origin_index: int = Field(ge=0)
    destination_index: int = Field(ge=0)
    status: str = Field(min_length=1)
    distance_meters: int | None = Field(
        default=None,
        ge=0,
    )
    duration_seconds: int | None = Field(
        default=None,
        ge=0,
    )


class DistanceMatrixRow(StrictModel):
    origin_index: int = Field(ge=0)
    elements: list[DistanceMatrixElement] = Field(
        min_length=1,
        max_length=10,
    )


class DistanceMatrixResult(StrictModel):
    requested_mode: TravelMode
    provider: str = "goong"
    provider_vehicle: str
    origins: list[ResolvedRouteLocation] = Field(
        min_length=1,
        max_length=10,
    )
    destinations: list[ResolvedRouteLocation] = Field(
        min_length=1,
        max_length=10,
    )
    rows: list[DistanceMatrixRow] = Field(
        min_length=1,
        max_length=10,
    )

    @model_validator(mode="after")
    def validate_matrix_shape(self) -> DistanceMatrixResult:
        if len(self.rows) != len(self.origins):
            raise ValueError(
                "Distance matrix row count must match origins."
            )

        destination_count = len(self.destinations)

        for origin_index, row in enumerate(self.rows):
            if row.origin_index != origin_index:
                raise ValueError(
                    "Distance matrix rows must use contiguous "
                    "origin indexes."
                )

            if len(row.elements) != destination_count:
                raise ValueError(
                    "Each distance matrix row must contain one "
                    "element per destination."
                )

            for destination_index, element in enumerate(
                row.elements
            ):
                if (
                    element.origin_index != origin_index
                    or element.destination_index
                    != destination_index
                ):
                    raise ValueError(
                        "Distance matrix element indexes do not "
                        "match their row and column positions."
                    )

        return self


# ============================================================
# WEATHER
# ============================================================

# OpenWeather Free 5-day/3-hour forecast: today (0) through +4.
WEATHER_MAX_FORECAST_OFFSET_DAYS = 4


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
# CONVERSATION CONSTRAINTS / CLARIFICATION
# ============================================================


class ConstraintSource(str, Enum):
    """
    Nguồn của một constraint được extract.

    Precedence sẽ do ContextBuilder xử lý sau này, không nằm
    trong schema này.
    """

    CURRENT_MESSAGE = "current_message"
    CONVERSATION = "conversation"
    CLARIFICATION = "clarification"
    INFERRED = "inferred"


class RequirementLevel(str, Enum):
    """
    Mức độ cần thiết của một field còn thiếu.
    """

    BLOCKING = "blocking"
    IMPORTANT = "important"
    OPTIONAL = "optional"


class ClarificationAnswerType(str, Enum):
    """
    Kiểu input frontend có thể gợi ý cho user.

    User vẫn luôn có thể trả lời bằng natural-language message.
    """

    FREE_TEXT = "free_text"
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    NUMBER = "number"
    DATE = "date"


class ExtractedConstraint(StrictModel):
    """
    Một constraint đã được extract từ message hoặc conversation.
    """

    key: str = Field(
        min_length=1,
    )

    value: Any

    source: ConstraintSource

    explicit: bool = False


class ClarificationOption(StrictModel):
    """
    Suggested answer option. Đây là convenience cho frontend,
    không giới hạn natural-language answer của user.
    """

    label: str = Field(
        min_length=1,
    )

    value: Any

    description: str | None = None


class ClarificationField(StrictModel):
    """
    Một field mà clarification policy muốn hỏi user.
    """

    key: str = Field(
        min_length=1,
    )

    question: str = Field(
        min_length=1,
    )

    requirement: RequirementLevel

    answer_type: ClarificationAnswerType = (
        ClarificationAnswerType.FREE_TEXT
    )

    options: list[ClarificationOption] = Field(
        default_factory=list,
    )


class ClarificationRequest(StrictModel):
    """
    Structured clarification payload dành cho frontend.
    """

    question: str = Field(
        min_length=1,
    )

    fields: list[ClarificationField] = Field(
        min_length=1,
        max_length=2,
    )


class ClarificationDecision(StrictModel):
    """
    Internal deterministic policy result.

    ClarificationRequest là phần có thể trả về frontend; hai danh
    sách missing fields phục vụ debugging và policy evaluation.
    """

    blocking_fields: list[ClarificationField] = Field(
        default_factory=list,
    )

    important_missing_fields: list[
        ClarificationField
    ] = Field(
        default_factory=list,
    )

    clarification: ClarificationRequest | None = None

    @property
    def needs_clarification(self) -> bool:
        return self.clarification is not None


# ============================================================
# EXECUTION PLAN
# ============================================================

class ExecutionPlan(StrictModel):

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

    research_depth: ResearchDepth = (
        ResearchDepth.BASIC
    )

    response_modifier: ResponseModifier | None = None

    subtasks: list[SubTask] = Field(
        default_factory=list,
    )

    fallback_to_web: bool = False

    require_all_entities: bool = False

    coverage_entities: list[str] = Field(
        default_factory=list,
    )

    constraints: list[ExtractedConstraint] = Field(
        default_factory=list,
    )

    clarification: ClarificationRequest | None = None

    @property
    def needs_clarification(self) -> bool:
        return self.clarification is not None

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
# REASONER
# ============================================================


class ReasonerPoint(StrictModel):
    """
    Một claim/khuyến nghị với grounding riêng.

    IDs chỉ được chứa các nguồn trực tiếp hỗ trợ point này.
    """

    text: str

    evidence_ids: list[str] = Field(
        default_factory=list,
    )

    observation_task_ids: list[str] = Field(
        default_factory=list,
    )


class ReasonerSection(StrictModel):
    """
    Một section trong structured answer plan.

    Đây là output structure, không phải chain-of-thought.
    """

    heading: str

    purpose: str

    points: list[ReasonerPoint] = Field(
        default_factory=list,
    )


class ReasonerOutput(StrictModel):
    """
    Structured answer plan được Synthesizer sử dụng.

    Model này chỉ lưu kết luận có cấu trúc và references,
    không lưu chain-of-thought.
    """

    answer_type: str

    answer_goal: str

    sections: list[ReasonerSection] = Field(
        default_factory=list,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    limitations: list[str] = Field(
        default_factory=list,
    )

    used_evidence_ids: list[str] = Field(
        default_factory=list,
    )

    used_observation_task_ids: list[str] = Field(
        default_factory=list,
    )

    degraded: bool = False


# ============================================================
# SYNTHESIZER / FINAL RESPONSE
# ============================================================


class SynthesizerOutput(StrictModel):
    """
    Draft do LLM tạo.

    Citation vẫn dùng internal marker:

        [[evidence:<evidence_id>]]
        [[tool:<task_id>]]

    Citation resolver sẽ xử lý deterministic sau.
    """

    answer_markdown: str

    suggested_followups: list[str] = Field(
        default_factory=list,
    )


class Citation(StrictModel):
    """
    Citation mà frontend có thể render thành source card.
    """

    citation_id: str

    evidence_id: str | None = None

    task_id: str | None = None

    title: str

    url: str | None = None

    source_type: EvidenceSource

    tool: ToolName | None = None

    provider: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_source_reference(self) -> Citation:
        has_evidence = self.evidence_id is not None
        has_task = self.task_id is not None

        if has_evidence == has_task:
            raise ValueError(
                "Citation requires exactly one of "
                "evidence_id or task_id."
            )

        return self


class AgentResponseType(str, Enum):
    ANSWER = "answer"
    CLARIFICATION = "clarification"


class AgentResponse(StrictModel):
    """
    Output cuối của agent service.

    Sau này FastAPI /chat có thể trả cấu trúc này.
    """

    response_type: AgentResponseType = (
        AgentResponseType.ANSWER
    )

    answer: str = ""

    clarification: ClarificationRequest | None = None

    citations: list[Citation] = Field(
        default_factory=list,
    )

    intent: Intent | None = None

    used_tools: list[ToolName] = Field(
        default_factory=list,
    )

    suggested_followups: list[str] = Field(
        default_factory=list,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    degraded: bool = False

    @model_validator(mode="after")
    def validate_response_payload(self) -> AgentResponse:
        has_clarification = self.clarification is not None

        if (
            self.response_type
            == AgentResponseType.CLARIFICATION
            and not has_clarification
        ):
            raise ValueError(
                "Clarification response requires "
                "a clarification payload."
            )

        if (
            self.response_type
            == AgentResponseType.ANSWER
            and has_clarification
        ):
            raise ValueError(
                "Answer response cannot include "
                "a clarification payload."
            )

        return self
    
# ============================================================
# BUDGET
# ============================================================


class BudgetRequest(StrictModel):
    """
    Deterministic budget calculation input.

    Tất cả cost field là TOTAL cost cho toàn chuyến đi,
    không phải cost/ngày hoặc cost/người.

    BudgetTool không được tự đoán giá.
    """

    currency: str = "VND"

    travelers: int = Field(
        default=1,
        ge=1,
    )

    days: int = Field(
        default=1,
        ge=1,
    )

    total_budget: float | None = Field(
        default=None,
        ge=0,
    )

    intercity_transport_cost: float = Field(
        default=0,
        ge=0,
    )

    accommodation_cost: float = Field(
        default=0,
        ge=0,
    )

    food_cost: float = Field(
        default=0,
        ge=0,
    )

    ticket_cost: float = Field(
        default=0,
        ge=0,
    )

    local_transport_cost: float = Field(
        default=0,
        ge=0,
    )

    other_cost: float = Field(
        default=0,
        ge=0,
    )

    original_query: str | None = None

    @field_validator(
        "total_budget",
        "intercity_transport_cost",
        "accommodation_cost",
        "food_cost",
        "ticket_cost",
        "local_transport_cost",
        "other_cost",
        mode="before",
    )
    @classmethod
    def normalize_money_amount(cls, value: Any) -> Any:
        if value is None or isinstance(value, (int, float)):
            return value
        if not isinstance(value, str):
            return value

        text_value = value.strip().casefold()
        if not text_value:
            return value

        multiplier = 1.0
        units = (
            (("tỷ", "ty"), 1_000_000_000.0),
            (("triệu", "trieu"), 1_000_000.0),
            (("nghìn", "nghin", "ngàn", "ngan", "k"), 1_000.0),
        )
        for names, candidate_multiplier in units:
            if any(re.search(rf"\b{re.escape(name)}\b", text_value) for name in names):
                multiplier = candidate_multiplier
                break

        numeric_text = re.sub(r"[^0-9,.-]", "", text_value)
        if not numeric_text:
            return value

        if multiplier != 1.0:
            numeric_text = numeric_text.replace(".", "").replace(",", ".")
        else:
            numeric_text = numeric_text.replace(".", "").replace(",", "")

        try:
            return float(numeric_text) * multiplier
        except ValueError:
            return value
