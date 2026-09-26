from __future__ import annotations

from pipeline.agents.schemas import (
    BudgetRequest,
    SubTask,
    TaskStatus,
    ToolName,
)
from pipeline.agents.tools import (
    BudgetTool,
    ToolRegistry,
)


def run_case(
    *,
    name: str,
    request: BudgetRequest,
    expected_status: TaskStatus,
):
    tool = BudgetTool()
    result = tool.execute(
        task_id=name,
        request=request,
    )

    print()
    print("=" * 90)
    print(name)
    print("=" * 90)
    print(result.model_dump_json(indent=2))

    assert result.status == expected_status, result.error
    return result


def main() -> None:
    # ========================================================
    # 1. WITHIN TARGET BUDGET
    # ========================================================

    within_budget = run_case(
        name="WITHIN_BUDGET",
        request=BudgetRequest(
            currency="VND",
            travelers=2,
            days=3,
            total_budget=5_000_000,
            intercity_transport_cost=800_000,
            accommodation_cost=1_400_000,
            food_cost=1_200_000,
            ticket_cost=600_000,
            local_transport_cost=500_000,
            other_cost=200_000,
        ),
        expected_status=TaskStatus.SUCCESS,
    )

    assert within_budget.data["estimated_total"] == 4_700_000
    assert within_budget.data["remaining_budget"] == 300_000
    assert within_budget.data["over_budget_by"] == 0
    assert within_budget.data["within_budget"] is True
    assert within_budget.data["cost_per_person"] == 2_350_000
    assert within_budget.data["cost_per_day"] == 1_566_666.67

    # ========================================================
    # 2. OVER TARGET BUDGET
    # ========================================================

    over_budget = run_case(
        name="OVER_BUDGET",
        request=BudgetRequest(
            currency="VND",
            travelers=2,
            days=3,
            total_budget=4_000_000,
            intercity_transport_cost=800_000,
            accommodation_cost=1_400_000,
            food_cost=1_200_000,
            ticket_cost=600_000,
            local_transport_cost=500_000,
            other_cost=200_000,
        ),
        expected_status=TaskStatus.SUCCESS,
    )

    assert over_budget.data["within_budget"] is False
    assert over_budget.data["remaining_budget"] == 0
    assert over_budget.data["over_budget_by"] == 700_000

    # ========================================================
    # 3. CALCULATE WITHOUT TARGET BUDGET
    # ========================================================

    no_target = run_case(
        name="NO_TARGET_BUDGET",
        request=BudgetRequest(
            currency="VND",
            travelers=1,
            days=2,
            accommodation_cost=800_000,
            food_cost=500_000,
            ticket_cost=300_000,
        ),
        expected_status=TaskStatus.SUCCESS,
    )

    assert no_target.data["estimated_total"] == 1_600_000
    assert no_target.data["within_budget"] is None
    assert no_target.data["remaining_budget"] is None
    assert no_target.data["over_budget_by"] is None

    # ========================================================
    # 4. INSUFFICIENT INPUT
    # ========================================================

    insufficient = run_case(
        name="INSUFFICIENT_INPUT",
        request=BudgetRequest(
            currency="VND",
            travelers=2,
            days=3,
            total_budget=5_000_000,
        ),
        expected_status=TaskStatus.FAILED,
    )

    assert (
        insufficient.data["error_code"]
        == "BUDGET_INPUT_INSUFFICIENT"
    )

    # ========================================================
    # 5. REGISTRY DISPATCH
    # ========================================================

    registry_request = BudgetRequest(
        currency="VND",
        total_budget=5_000_000,
        travelers=2,
        days=3,
        accommodation_cost=1_400_000,
        food_cost=1_200_000,
        ticket_cost=600_000,
    )

    registry_result = ToolRegistry().execute(
        SubTask(
            task_id="budget_1",
            description="Calculate trip budget",
            tool=ToolName.BUDGET,
            arguments=registry_request.model_dump(),
        )
    )

    assert registry_result.status == TaskStatus.SUCCESS, (
        registry_result.error
    )
    assert registry_result.task_id == "budget_1"
    assert registry_result.tool == ToolName.BUDGET
    assert registry_result.data["estimated_total"] == 3_200_000

    print()
    print("=" * 90)
    print("ALL BUDGET TOOL TESTS PASSED")
    print("=" * 90)


if __name__ == "__main__":
    main()
