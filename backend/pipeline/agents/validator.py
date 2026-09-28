from __future__ import annotations

from pipeline.agents.schemas import (
    EvidenceItem,
    ExecutionPlan,
    TaskStatus,
    ToolName,
    ToolObservation,
    ValidationIssue,
    ValidationResult,
)


# ============================================================
# AGENT VALIDATOR
# ============================================================


class AgentValidator:
    """
    Deterministic validation sau ToolExecutor.

    Responsibilities:

        1. required task có observation hay không
        2. required task SUCCESS hay không
        3. research task có evidence hay không
        4. entity coverage có đủ hay không
        5. specialized tool SUCCESS nhưng data rỗng hay không
        6. phân loại issue recoverable / non-recoverable

    Không:

        - gọi LLM
        - execute tool
        - retry
        - mutate ExecutionPlan
        - reasoning
        - synthesis
    """

    # ========================================================
    # ERROR CODES THAT SHOULD NOT BE RETRIED
    # ========================================================

    NON_RECOVERABLE_TOOL_ERRORS = {
        # Weather provider/product capability.
        "WEATHER_FORECAST_OUT_OF_RANGE",
        "WEATHER_HISTORY_UNSUPPORTED",

        # Budget requires normalized cost estimates upstream.
        "BUDGET_INPUT_INSUFFICIENT",

        # Structural dependency error propagated by executor.
        "DEPENDENCY_FAILED",

        # Routing deterministic failures.
        "ROUTING_MODE_UNSUPPORTED",
        "ROUTING_INVALID_ARGUMENTS",
        "ROUTING_ORIGIN_NOT_FOUND",
        "ROUTING_DESTINATION_NOT_FOUND",
        "ROUTING_NO_ROUTE",
    }

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _observation_map(
        observations: list[ToolObservation],
    ) -> dict[str, ToolObservation]:
        """
        task_id -> ToolObservation
        """

        return {
            observation.task_id: observation
            for observation in observations
        }

    # ========================================================
    # TOOL ERROR RECOVERABILITY
    # ========================================================

    def _is_recoverable_tool_failure(
        self,
        observation: ToolObservation,
    ) -> bool:

        error_code = (
            observation
            .data
            .get("error_code")
        )

        if (
            isinstance(error_code, str)
            and error_code
            in self.NON_RECOVERABLE_TOOL_ERRORS
        ):
            return False

        return True

    # ========================================================
    # REQUIRED TASKS
    # ========================================================

    def _validate_required_tasks(
        self,
        *,
        plan: ExecutionPlan,
        observation_map: dict[
            str,
            ToolObservation,
        ],
    ) -> list[ValidationIssue]:

        issues: list[
            ValidationIssue
        ] = []

        for task in plan.subtasks:

            if not task.required:
                continue

            observation = (
                observation_map.get(
                    task.task_id
                )
            )

            # -----------------------------------------------
            # Missing observation
            # -----------------------------------------------

            if observation is None:

                issues.append(
                    ValidationIssue(
                        code=(
                            "REQUIRED_TASK_MISSING"
                        ),

                        message=(
                            "Required task did not "
                            "produce a ToolObservation."
                        ),

                        task_id=(
                            task.task_id
                        ),

                        recoverable=True,
                    )
                )

                continue

            # -----------------------------------------------
            # Success
            # -----------------------------------------------

            if (
                observation.status
                == TaskStatus.SUCCESS
            ):
                continue

            # -----------------------------------------------
            # Failed / skipped
            # -----------------------------------------------

            error_code = (
                observation
                .data
                .get("error_code")
            )

            code = (
                str(error_code)
                if error_code
                else (
                    "REQUIRED_TASK_"
                    f"{observation.status.value}"
                )
            )

            issues.append(
                ValidationIssue(
                    code=code,

                    message=(
                        observation.error
                        or (
                            "Required task did not "
                            "complete successfully."
                        )
                    ),

                    task_id=(
                        task.task_id
                    ),

                    recoverable=(
                        self
                        ._is_recoverable_tool_failure(
                            observation
                        )
                    ),
                )
            )

        return issues

    # ========================================================
    # RESEARCH VALIDATION
    # ========================================================

    @staticmethod
    def _validate_research(
        *,
        plan: ExecutionPlan,
        observations: list[
            ToolObservation
        ],
        research_evidence: list[
            EvidenceItem
        ],
    ) -> list[ValidationIssue]:

        issues: list[
            ValidationIssue
        ] = []

        rag_tasks = [
            task
            for task in plan.subtasks
            if (
                task.tool
                == ToolName.RAG
            )
        ]

        # Không có knowledge task thì research evidence
        # không bắt buộc.
        if not rag_tasks:
            return issues

        successful_rag = [
            observation
            for observation
            in observations
            if (
                observation.tool
                == ToolName.RAG
                and observation.status
                == TaskStatus.SUCCESS
            )
        ]

        # Required task failure đã được check ở method khác.
        # Ở đây chỉ check quality nếu RAG thực sự SUCCESS.
        if (
            successful_rag
            and not research_evidence
        ):

            issues.append(
                ValidationIssue(
                    code=(
                        "RESEARCH_EVIDENCE_EMPTY"
                    ),

                    message=(
                        "Research task succeeded "
                        "but no RAG/WEB evidence "
                        "remained after aggregation."
                    ),

                    task_id=(
                        successful_rag[0]
                        .task_id
                    ),

                    recoverable=True,
                )
            )

        return issues

    # ========================================================
    # ENTITY COVERAGE
    # ========================================================

    @staticmethod
    def _validate_entity_coverage(
        *,
        plan: ExecutionPlan,
        observations: list[
            ToolObservation
        ],
    ) -> list[ValidationIssue]:

        issues: list[
            ValidationIssue
        ] = []

        if not (
            plan.require_all_entities
        ):
            return issues

        required_entities = (
            plan.coverage_entities
            or plan.entities
        )

        if not required_entities:
            return issues

        rag_observations = [
            observation
            for observation
            in observations
            if (
                observation.tool
                == ToolName.RAG
                and observation.status
                == TaskStatus.SUCCESS
            )
        ]

        # Nếu RAG task failed thì required-task validation
        # đã tạo issue rồi.
        if not rag_observations:
            return issues

        covered_entities: set[
            str
        ] = set()

        missing_entities: set[
            str
        ] = set()

        found_coverage = False

        for observation in (
            rag_observations
        ):

            coverage = (
                observation.coverage
            )

            if coverage is not None:

                found_coverage = True

                covered_entities.update(
                    coverage.covered_entities
                )

                missing_entities.update(
                    coverage.missing_entities
                )

                continue

            # Fallback cho implementation knowledge tool
            # đang expose coverage trong data.
            data_covered = (
                observation
                .data
                .get(
                    "covered_entities",
                    [],
                )
            )

            data_missing = (
                observation
                .data
                .get(
                    "missing_entities",
                    [],
                )
            )

            if (
                data_covered
                or data_missing
            ):

                found_coverage = True

                covered_entities.update(
                    str(item)
                    for item
                    in data_covered
                )

                missing_entities.update(
                    str(item)
                    for item
                    in data_missing
                )

        # -----------------------------------------------
        # Coverage metadata missing
        # -----------------------------------------------

        if not found_coverage:

            issues.append(
                ValidationIssue(
                    code=(
                        "ENTITY_COVERAGE_UNKNOWN"
                    ),

                    message=(
                        "Plan requires entity "
                        "coverage but successful "
                        "research observation did "
                        "not provide coverage data."
                    ),

                    task_id=(
                        rag_observations[0]
                        .task_id
                    ),

                    recoverable=True,
                )
            )

            return issues

        # -----------------------------------------------
        # Normalize comparison
        # -----------------------------------------------

        def normalize(
            value: str,
        ) -> str:

            return (
                value
                .strip()
                .casefold()
            )

        covered_normalized = {
            normalize(item)
            for item
            in covered_entities
        }

        missing_from_required = [
            entity
            for entity
            in required_entities
            if (
                normalize(entity)
                not in covered_normalized
            )
        ]

        # Prefer explicit missing_entities where available,
        # nhưng derive từ required-vs-covered để tránh
        # metadata inconsistency.
        final_missing = list(
            dict.fromkeys(
                [
                    *missing_from_required,
                    *sorted(
                        missing_entities,
                        key=normalize,
                    ),
                ]
            )
        )

        if final_missing:

            issues.append(
                ValidationIssue(
                    code=(
                        "ENTITY_COVERAGE_INCOMPLETE"
                    ),

                    message=(
                        "Missing research coverage "
                        "for entities: "
                        + ", ".join(
                            final_missing
                        )
                    ),

                    task_id=(
                        rag_observations[0]
                        .task_id
                    ),

                    recoverable=True,
                )
            )

        return issues

    # ========================================================
    # SPECIALIZED TOOL DATA
    # ========================================================

    @staticmethod
    def _validate_specialized_data(
        observations: list[
            ToolObservation
        ],
    ) -> list[ValidationIssue]:

        issues: list[
            ValidationIssue
        ] = []

        specialized_tools = {
            ToolName.WEATHER,
            ToolName.ROUTING,
            ToolName.MAP_LOCATION,
            ToolName.BUDGET,
        }

        for observation in (
            observations
        ):

            if (
                observation.tool
                not in specialized_tools
            ):
                continue

            if (
                observation.status
                != TaskStatus.SUCCESS
            ):
                continue

            if observation.data:
                continue

            issues.append(
                ValidationIssue(
                    code=(
                        "SPECIALIZED_TOOL_DATA_EMPTY"
                    ),

                    message=(
                        "Specialized tool returned "
                        "SUCCESS but data is empty."
                    ),

                    task_id=(
                        observation.task_id
                    ),

                    recoverable=True,
                )
            )

        return issues

    # ========================================================
    # PUBLIC
    # ========================================================

    def validate(
        self,
        *,
        plan: ExecutionPlan,
        observations: list[
            ToolObservation
        ],
        research_evidence: list[
            EvidenceItem
        ],
    ) -> ValidationResult:

        observation_map = (
            self._observation_map(
                observations
            )
        )

        issues: list[
            ValidationIssue
        ] = []

        # ----------------------------------------------------
        # Required tasks
        # ----------------------------------------------------

        issues.extend(
            self._validate_required_tasks(
                plan=plan,
                observation_map=(
                    observation_map
                ),
            )
        )

        # ----------------------------------------------------
        # Research quality
        # ----------------------------------------------------

        issues.extend(
            self._validate_research(
                plan=plan,
                observations=observations,
                research_evidence=(
                    research_evidence
                ),
            )
        )

        # ----------------------------------------------------
        # Entity coverage
        # ----------------------------------------------------

        issues.extend(
            self._validate_entity_coverage(
                plan=plan,
                observations=observations,
            )
        )

        # ----------------------------------------------------
        # Specialized data
        # ----------------------------------------------------

        issues.extend(
            self._validate_specialized_data(
                observations
            )
        )

        return ValidationResult(
            valid=(
                len(issues) == 0
            ),

            issues=issues,
        )
