from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.agents.schemas import (
    BudgetRequest,
    ResearchDepth,
    SubTask,
    TaskStatus,
    ToolName,
    ToolObservation,
    WeatherRequest,
)

from .budget import BudgetTool, normalize_budget_arguments
from .distance_matrix import DistanceMatrixTool
from .map_location import MapLocationTool
from .routing import RoutingTool
from .weather import WeatherTool
from .web import WebSearchTool

if TYPE_CHECKING:
    from .knowledge import TravelKnowledgeTool


logger = logging.getLogger(__name__)


# ============================================================
# TOOL REGISTRY
# ============================================================

class ToolRegistry:
    """
    Single execution boundary cho Agent System.

    Planner chỉ tạo SubTask.

    LangGraph sau này chỉ gọi:

        registry.execute(task)

    Registry chịu trách nhiệm dispatch tới đúng tool.

    Hiện implement thật:
        - search_travel_knowledge
        - web_search
        - weather
        - budget_calculator
        - map_location
        - routing
        - distance_matrix

    Các tool khác sẽ được fill dần:
        - trip_optimization
    """

    def __init__(
        self,
        web_tool: WebSearchTool | None = None,
        *,
        map_location_tool: MapLocationTool | None = None,
        routing_tool: RoutingTool | None = None,
        distance_matrix_tool: DistanceMatrixTool | None = None,
    ) -> None:
        """
        Dependencies vẫn lazy.

        web_tool có thể được inject từ ToolRegistry
        để direct web search và RAG fallback
        dùng chung một Tavily client.
        """

        self._web: (
            WebSearchTool | None
        ) = web_tool

        self._knowledge: (
            TravelKnowledgeTool | None
        ) = None

        self._weather: (
            WeatherTool | None
        ) = None

        self._budget: (
            BudgetTool | None
        ) = None

        self._map_location_tool = (
            map_location_tool
        )

        self._routing_tool = routing_tool

        self._distance_matrix_tool = distance_matrix_tool

    # ========================================================
    # LAZY DEPENDENCIES
    # ========================================================

    @property
    def web(
        self,
    ) -> WebSearchTool:

        if self._web is None:

            if self._knowledge is not None:
                self._web = (
                    self._knowledge.web
                )
            else:
                self._web = (
                    WebSearchTool()
                )

        return self._web

    @property
    def knowledge(
        self,
    ) -> TravelKnowledgeTool:

        if self._knowledge is None:

            from .knowledge import (
                TravelKnowledgeTool,
            )

            self._knowledge = (
                TravelKnowledgeTool(
                    web_tool=self._web
                )
            )

        return self._knowledge

    @property
    def weather(
        self,
    ) -> WeatherTool:

        if self._weather is None:

            self._weather = (
                WeatherTool()
            )

        return self._weather

    @property
    def budget(
        self,
    ) -> BudgetTool:

        if self._budget is None:

            self._budget = (
                BudgetTool()
            )

        return self._budget

    @property
    def map_location_tool(
        self,
    ) -> MapLocationTool:

        if self._map_location_tool is None:

            self._map_location_tool = (
                MapLocationTool()
            )

        return self._map_location_tool

    @property
    def routing_tool(
        self,
    ) -> RoutingTool:

        if self._routing_tool is None:

            self._routing_tool = RoutingTool()

        return self._routing_tool

    @property
    def distance_matrix_tool(
        self,
    ) -> DistanceMatrixTool:

        if self._distance_matrix_tool is None:

            self._distance_matrix_tool = (
                DistanceMatrixTool()
            )

        return self._distance_matrix_tool

    # ========================================================
    # FAILED OBSERVATION
    # ========================================================

    @staticmethod
    def _failed(
        *,
        task: SubTask,
        message: str,
    ) -> ToolObservation:

        return ToolObservation(
            task_id=task.task_id,

            tool=task.tool,

            status=TaskStatus.FAILED,

            error=message,

            source_count=0,
        )

    # ========================================================
    # TRAVEL KNOWLEDGE
    # ========================================================

    def _execute_rag(
        self,
        task: SubTask,
        research_depth: (
            ResearchDepth | str | None
        ) = None,
    ) -> ToolObservation:

        arguments = (
            task.arguments
        )

        query = str(
            arguments.get(
                "query",
                "",
            )
        ).strip()

        raw_entities = arguments.get(
            "entities",
            [],
        )

        if not isinstance(
            raw_entities,
            list,
        ):

            return self._failed(
                task=task,
                message=(
                    "'entities' phải là list."
                ),
            )

        entities = [
            str(entity).strip()
            for entity in raw_entities
            if str(entity).strip()
        ]

        require_all_entities = bool(
            arguments.get(
                "require_all_entities",
                False,
            )
        )

        raw_research_depth = (
            research_depth
            if research_depth is not None
            else arguments.get(
                "research_depth",
                ResearchDepth.BASIC,
            )
        )

        try:
            resolved_research_depth = (
                raw_research_depth
                if isinstance(
                    raw_research_depth,
                    ResearchDepth,
                )
                else ResearchDepth(
                    str(raw_research_depth)
                )
            )
        except ValueError:
            return self._failed(
                task=task,
                message=(
                    "'research_depth' phải là "
                    "BASIC, ENRICHED hoặc DEEP."
                ),
            )

        if not query:

            return self._failed(
                task=task,
                message=(
                    "search_travel_knowledge "
                    "thiếu argument 'query'."
                ),
            )

        return self.knowledge.search(
            task_id=task.task_id,

            query=query,

            entities=entities,

            require_all_entities=(
                require_all_entities
            ),

            research_depth=(
                resolved_research_depth
            ),
        )
    # ========================================================
    # WEB SEARCH
    # ========================================================

    def _execute_web(
        self,
        task: SubTask,
    ) -> ToolObservation:

        arguments = (
            task.arguments
        )

        query = str(
            arguments.get(
                "query",
                "",
            )
        ).strip()

        entity_raw = arguments.get(
            "entity"
        )

        entity = (
            str(entity_raw).strip()
            if entity_raw is not None
            else None
        )

        if entity == "":
            entity = None

        if not query:

            return self._failed(
                task=task,
                message=(
                    "web_search thiếu "
                    "argument 'query'."
                ),
            )

        try:

            evidence = (
                self.web.search(
                    query=query,
                    entity=entity,
                )
            )

        except Exception as exc:

            return self._failed(
                task=task,
                message=(
                    f"Web search failed: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )

        if not evidence:

            return self._failed(
                task=task,
                message=(
                    "Web search không tìm "
                    "được evidence phù hợp."
                ),
            )

        return ToolObservation(
            task_id=task.task_id,

            tool=task.tool,

            status=TaskStatus.SUCCESS,

            data={
                "query": query,
                "entity": entity,
                "provider": "tavily",
            },

            evidence=evidence,

            coverage=None,

            error=None,

            source_count=len(
                evidence
            ),
        )

    # ========================================================
    # WEATHER
    # ========================================================

    def _execute_weather(
        self,
        task: SubTask,
    ) -> ToolObservation:

        try:

            request = (
                WeatherRequest
                .model_validate(
                    task.arguments
                )
            )

        except Exception as exc:
            return self._failed(
                task=task,

                message=(
                    "Weather arguments không hợp lệ: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )

        return self.weather.execute(
            task_id=task.task_id,

            request=request,
        )

    # ========================================================
    # BUDGET
    # ========================================================

    def _execute_budget(
        self,
        task: SubTask,
    ) -> ToolObservation:

        try:

            request = (
                BudgetRequest
                .model_validate(
                    normalize_budget_arguments(task.arguments)
                )
            )

        except Exception as exc:

            logger.warning(
                "Budget argument normalization failure",
                extra={"argument_fields": sorted(task.arguments)},
            )

            return self._failed(
                task=task,

                message=(
                    "Budget arguments không hợp lệ: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )

        return self.budget.execute(
            task_id=task.task_id,

            request=request,
        )

    # ========================================================
    # PUBLIC EXECUTE
    # ========================================================

    def execute(
        self,
        task: SubTask,
        *,
        research_depth: (
            ResearchDepth | str | None
        ) = None,
    ) -> ToolObservation:
        """
        Dispatch một SubTask tới implementation thật.
        """

        try:

            if task.tool == ToolName.RAG:

                return self._execute_rag(
                    task,
                    research_depth=(
                        research_depth
                    ),
                )

            if (
                task.tool
                == ToolName.WEB_SEARCH
            ):

                return self._execute_web(
                    task
                )

            if (
                task.tool
                == ToolName.WEATHER
            ):

                return self._execute_weather(
                    task
                )

            if (
                task.tool
                == ToolName.BUDGET
            ):

                return self._execute_budget(
                    task
                )

            if (
                task.tool
                == ToolName.MAP_LOCATION
            ):

                return (
                    self.map_location_tool
                    .execute(
                        task
                    )
                )

            if (
                task.tool
                == ToolName.ROUTING
            ):

                return (
                    self.routing_tool
                    .execute(
                        task
                    )
                )

            if (
                task.tool
                == ToolName.DISTANCE_MATRIX
            ):

                return (
                    self.distance_matrix_tool
                    .execute(
                        task
                    )
                )

            # -----------------------------------------------
            # Chưa implement.
            #
            # Không fake result.
            # Không silently fallback sang Gemini/web.
            # -----------------------------------------------

            return self._failed(
                task=task,
                message=(
                    "Tool chưa được implement: "
                    f"{task.tool.value}"
                ),
            )

        except Exception as exc:

            return self._failed(
                task=task,
                message=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )
