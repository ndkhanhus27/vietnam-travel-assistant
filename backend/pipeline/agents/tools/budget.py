from __future__ import annotations

from typing import Any

from pipeline.agents.schemas import (
    BudgetRequest,
    TaskStatus,
    ToolName,
    ToolObservation,
)


# ============================================================
# BUDGET TOOL
# ============================================================


class BudgetTool:
    """
    Deterministic travel budget calculator.

    Responsibilities:

        - sum cost categories
        - compare estimated total with budget
        - calculate remaining / over budget
        - calculate per-person / per-day costs

    Không:

        - dùng LLM
        - search Web
        - search RAG
        - tự đoán giá
        - tự tạo cost estimate
    """

    # ========================================================
    # FAILED RESULT
    # ========================================================

    @staticmethod
    def _failed(
        *,
        task_id: str,
        code: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> ToolObservation:

        payload = dict(
            data or {}
        )

        payload[
            "error_code"
        ] = code

        return ToolObservation(
            task_id=task_id,

            tool=ToolName.BUDGET,

            status=TaskStatus.FAILED,

            data=payload,

            evidence=[],

            coverage=None,

            error=message,

            source_count=0,
        )

    # ========================================================
    # MONEY
    # ========================================================

    @staticmethod
    def _round_money(
        value: float,
    ) -> float:
        """
        Giữ deterministic output.

        Với VND thường số nguyên, nhưng schema vẫn cho float
        để không khóa tool vào một currency duy nhất.
        """

        return round(
            float(value),
            2,
        )

    # ========================================================
    # PUBLIC
    # ========================================================

    def execute(
        self,
        *,
        task_id: str,
        request: BudgetRequest,
    ) -> ToolObservation:

        # ====================================================
        # COST BREAKDOWN
        # ====================================================

        costs = {
            "intercity_transport": (
                request
                .intercity_transport_cost
            ),

            "accommodation": (
                request
                .accommodation_cost
            ),

            "food": (
                request
                .food_cost
            ),

            "tickets": (
                request
                .ticket_cost
            ),

            "local_transport": (
                request
                .local_transport_cost
            ),

            "other": (
                request
                .other_cost
            ),
        }

        estimated_total = sum(
            costs.values()
        )

        estimated_total = (
            self._round_money(
                estimated_total
            )
        )

        # ====================================================
        # NO COST DATA
        # ====================================================

        if estimated_total <= 0:

            return self._failed(
                task_id=task_id,

                code=(
                    "BUDGET_INPUT_INSUFFICIENT"
                ),

                message=(
                    "Budget calculation requires "
                    "at least one non-zero "
                    "cost estimate."
                ),

                data={
                    "currency": (
                        request.currency
                    ),

                    "travelers": (
                        request.travelers
                    ),

                    "days": (
                        request.days
                    ),

                    "total_budget": (
                        request.total_budget
                    ),
                },
            )

        # ====================================================
        # BASIC METRICS
        # ====================================================

        cost_per_person = (
            estimated_total
            / request.travelers
        )

        cost_per_day = (
            estimated_total
            / request.days
        )

        cost_per_person_per_day = (
            estimated_total
            / request.travelers
            / request.days
        )

        # ====================================================
        # BUDGET COMPARISON
        # ====================================================

        total_budget = (
            request.total_budget
        )

        within_budget: bool | None = None

        remaining_budget: (
            float | None
        ) = None

        over_budget_by: (
            float | None
        ) = None

        budget_utilization_percent: (
            float | None
        ) = None

        if total_budget is not None:

            remaining = (
                total_budget
                - estimated_total
            )

            within_budget = (
                remaining >= 0
            )

            remaining_budget = (
                self._round_money(
                    max(
                        remaining,
                        0,
                    )
                )
            )

            over_budget_by = (
                self._round_money(
                    max(
                        -remaining,
                        0,
                    )
                )
            )

            if total_budget > 0:

                budget_utilization_percent = (
                    round(
                        (
                            estimated_total
                            / total_budget
                        )
                        * 100,
                        2,
                    )
                )

        # ====================================================
        # NORMALIZE COSTS
        # ====================================================

        normalized_costs = {
            key: self._round_money(
                value
            )
            for key, value
            in costs.items()
        }

        # ====================================================
        # SUCCESS
        # ====================================================

        return ToolObservation(
            task_id=task_id,

            tool=ToolName.BUDGET,

            status=TaskStatus.SUCCESS,

            data={
                "provider": (
                    "deterministic_calculator"
                ),

                "currency": (
                    request.currency
                ),

                "travelers": (
                    request.travelers
                ),

                "days": (
                    request.days
                ),

                "costs": (
                    normalized_costs
                ),

                "estimated_total": (
                    estimated_total
                ),

                "total_budget": (
                    total_budget
                ),

                "within_budget": (
                    within_budget
                ),

                "remaining_budget": (
                    remaining_budget
                ),

                "over_budget_by": (
                    over_budget_by
                ),

                "budget_utilization_percent": (
                    budget_utilization_percent
                ),

                "cost_per_person": (
                    self._round_money(
                        cost_per_person
                    )
                ),

                "cost_per_day": (
                    self._round_money(
                        cost_per_day
                    )
                ),

                "cost_per_person_per_day": (
                    self._round_money(
                        cost_per_person_per_day
                    )
                ),

                "original_query": (
                    request.original_query
                ),
            },

            # Budget là structured deterministic data.
            # Không phải research evidence.
            evidence=[],

            coverage=None,

            error=None,

            source_count=1,
        )