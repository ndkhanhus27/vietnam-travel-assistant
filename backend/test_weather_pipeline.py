from __future__ import annotations

from pipeline.agents.planner import TravelPlanner

from pipeline.agents.schemas import (
    TaskStatus,
    ToolName,
    WeatherMode,
    WeatherRequest,
)

from pipeline.agents.tools import (
    ResearchEvidenceAggregator,
    ToolRegistry,
)


# ============================================================
# HELPERS
# ============================================================


def print_header(
    title: str,
) -> None:

    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


def find_weather_task(
    plan,
):
    """
    Không assume weather luôn là subtask[0].

    Sau này một query có thể có:

        RAG
        WEATHER
        BUDGET

    nên tìm theo ToolName.
    """

    for task in plan.subtasks:

        if (
            task.tool
            == ToolName.WEATHER
        ):
            return task

    return None


def run_weather_case(
    planner: TravelPlanner,
    registry: ToolRegistry,
    *,
    name: str,
    query: str,
    expected_mode: WeatherMode | None = None,
    expected_start: int | None = None,
    expected_end: int | None = None,
    expected_status: TaskStatus | None = None,
    expected_error_code: str | None = None,
) -> None:

    print_header(
        name
    )

    print(
        f"QUERY: {query}"
    )

    # ========================================================
    # PLANNER
    # ========================================================

    plan = planner.plan(
        query
    )

    print()
    print("PLAN:")

    print(
        plan.model_dump_json(
            indent=2,
        )
    )

    # ========================================================
    # FIND WEATHER TASK
    # ========================================================

    task = find_weather_task(
        plan
    )

    assert (
        task is not None
    ), (
        f"{name}: Planner không tạo "
        "WEATHER subtask."
    )

    print()
    print(
        f"WEATHER TASK ID : "
        f"{task.task_id}"
    )

    print(
        f"WEATHER TOOL    : "
        f"{task.tool.value}"
    )

    print(
        f"ARGUMENTS       : "
        f"{task.arguments}"
    )

    # ========================================================
    # VALIDATE WEATHER REQUEST
    # ========================================================

    request = (
        WeatherRequest
        .model_validate(
            task.arguments
        )
    )

    print()
    print("PARSED WEATHER REQUEST:")

    print(
        request.model_dump_json(
            indent=2,
        )
    )

    # ========================================================
    # ASSERT PLANNER OUTPUT
    # ========================================================

    if expected_mode is not None:

        assert (
            request.mode
            == expected_mode
        ), (
            f"{name}: expected mode "
            f"{expected_mode.value}, "
            f"got {request.mode.value}"
        )

    if expected_start is not None:

        assert (
            request.start_offset_days
            == expected_start
        ), (
            f"{name}: expected "
            f"start_offset_days="
            f"{expected_start}, "
            f"got "
            f"{request.start_offset_days}"
        )

    if expected_end is not None:

        assert (
            request.end_offset_days
            == expected_end
        ), (
            f"{name}: expected "
            f"end_offset_days="
            f"{expected_end}, "
            f"got "
            f"{request.end_offset_days}"
        )

    # ========================================================
    # EXECUTE THROUGH REGISTRY
    # ========================================================

    observation = (
        registry.execute(
            task,
            research_depth=(
                plan.research_depth
            ),
        )
    )

    print()
    print("TOOL OBSERVATION:")

    print(
        observation.model_dump_json(
            indent=2,
        )
    )

    # ========================================================
    # ASSERT EXECUTION RESULT
    # ========================================================

    if expected_status is not None:

        assert (
            observation.status
            == expected_status
        ), (
            f"{name}: expected status "
            f"{expected_status.value}, "
            f"got "
            f"{observation.status.value}"
        )

    if expected_error_code is not None:

        actual_error_code = (
            observation.data.get(
                "error_code"
            )
        )

        assert (
            actual_error_code
            == expected_error_code
        ), (
            f"{name}: expected "
            f"error_code="
            f"{expected_error_code}, "
            f"got "
            f"{actual_error_code}"
        )

    # ========================================================
    # IMPORTANT:
    # WEATHER MUST NOT ENTER RESEARCH AGGREGATOR
    # ========================================================

    aggregator = (
        ResearchEvidenceAggregator()
    )

    research_evidence = (
        aggregator.aggregate(
            [
                observation,
            ]
        )
    )

    assert (
        research_evidence
        == []
    ), (
        f"{name}: Weather evidence "
        "không được đi vào "
        "ResearchEvidenceAggregator."
    )

    print()
    print(
        "RESEARCH EVIDENCE: []"
    )

    print(
        "TEST RESULT: PASS"
    )


# ============================================================
# MAIN
# ============================================================


def main() -> None:

    planner = TravelPlanner()

    registry = ToolRegistry()

    # ========================================================
    # CASE 1
    # CURRENT
    # ========================================================

    run_weather_case(
        planner,
        registry,

        name="CURRENT",

        query=(
            "Thời tiết Đà Lạt "
            "hiện tại thế nào?"
        ),

        expected_mode=(
            WeatherMode.CURRENT
        ),

        expected_start=0,

        expected_end=0,

        expected_status=(
            TaskStatus.SUCCESS
        ),
    )

    # ========================================================
    # CASE 2
    # TOMORROW
    # ========================================================

    run_weather_case(
        planner,
        registry,

        name="TOMORROW",

        query=(
            "Ngày mai Đà Lạt "
            "có mưa không?"
        ),

        expected_mode=(
            WeatherMode.FORECAST
        ),

        expected_start=1,

        expected_end=1,

        expected_status=(
            TaskStatus.SUCCESS
        ),
    )

    # ========================================================
    # CASE 3
    # +3 DAYS
    # ========================================================

    run_weather_case(
        planner,
        registry,

        name="PLUS_3_DAYS",

        query=(
            "3 ngày nữa Đà Lạt "
            "có mưa không?"
        ),

        expected_mode=(
            WeatherMode.FORECAST
        ),

        expected_start=3,

        expected_end=3,

        expected_status=(
            TaskStatus.SUCCESS
        ),
    )

    # ========================================================
    # CASE 4
    # RANGE
    # ========================================================

    run_weather_case(
        planner,
        registry,

        name="NEXT_3_DAYS",

        query=(
            "Thời tiết Đà Lạt "
            "3 ngày tới thế nào?"
        ),

        expected_mode=(
            WeatherMode.FORECAST_RANGE
        ),

        expected_start=0,

        expected_end=3,

        expected_status=(
            TaskStatus.SUCCESS
        ),
    )

    # ========================================================
    # CASE 5
    # PLANNER MUST NOT CLAMP
    #
    # Gemini phải giữ:
    #
    #     15
    #
    # WeatherTool mới reject.
    # ========================================================

    run_weather_case(
        planner,
        registry,

        name="PLUS_15_DAYS",

        query=(
            "15 ngày nữa Đà Lạt "
            "có mưa không?"
        ),

        expected_mode=(
            WeatherMode.FORECAST
        ),

        expected_start=15,

        expected_end=15,

        expected_status=(
            TaskStatus.FAILED
        ),

        expected_error_code=(
            "WEATHER_FORECAST_OUT_OF_RANGE"
        ),
    )

    # ========================================================
    # CASE 6
    # HISTORY
    #
    # Planner hiểu được historical.
    #
    # Provider Free hiện không support,
    # nên WeatherTool reject.
    # ========================================================

    run_weather_case(
        planner,
        registry,

        name="YESTERDAY",

        query=(
            "Hôm qua Đà Lạt "
            "thời tiết thế nào?"
        ),

        expected_mode=(
            WeatherMode.RECENT_HISTORY
        ),

        expected_start=-1,

        expected_end=-1,

        expected_status=(
            TaskStatus.FAILED
        ),

        expected_error_code=(
            "WEATHER_HISTORY_UNSUPPORTED"
        ),
    )

    # ========================================================
    # DONE
    # ========================================================

    print()
    print("=" * 100)
    print(
        "ALL PLANNER -> REGISTRY -> "
        "WEATHER TESTS PASSED"
    )
    print("=" * 100)


if __name__ == "__main__":
    main()