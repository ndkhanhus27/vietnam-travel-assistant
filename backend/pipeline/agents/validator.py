from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from pipeline.agents.schemas import (
    EvidenceItem,
    EvidenceSource,
    ExecutionPlan,
    Intent,
    ResponseModifier,
    TaskStatus,
    ToolName,
    ToolObservation,
    ValidationIssue,
    ValidationResult,
)
from pipeline.agents.tools.utils import normalize_text


logger = logging.getLogger(__name__)


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
        "ROUTING_IMPLAUSIBLE",
        "ROUTING_AMBIGUOUS_GEOCODING",

        # Distance Matrix deterministic failures.
        "DISTANCE_MATRIX_MODE_UNSUPPORTED",
        "DISTANCE_MATRIX_INVALID_ARGUMENTS",
        "DISTANCE_MATRIX_LOCATION_NOT_FOUND",
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

    @staticmethod
    def _validate_recommendation_coverage(
        *,
        plan: ExecutionPlan,
        research_evidence: list[EvidenceItem],
    ) -> list[ValidationIssue]:
        if plan.intent != Intent.RECOMMENDATION:
            return []
        if plan.response_modifier == ResponseModifier.CONDENSE:
            return []

        rag_task = next(
            (task for task in plan.subtasks if task.tool == ToolName.RAG),
            None,
        )
        if rag_task is None:
            return []

        query = str(rag_task.arguments.get("query") or "").casefold()
        broad_markers = (
            "gợi ý",
            "nên đi đâu",
            "địa điểm",
            "chỗ nào",
            "nơi nào",
            "thêm",
        )
        is_broad = (
            plan.response_modifier == ResponseModifier.ADD_OPTIONS
            or any(marker in query for marker in broad_markers)
        )
        if not is_broad:
            return []

        distinct_sources = {item.evidence_id for item in research_evidence}
        if len(distinct_sources) >= 3:
            return []

        logger.info(
            "Recommendation evidence coverage requires expansion",
            extra={
                "intent": plan.intent.value,
                "response_modifier": (
                    plan.response_modifier.value
                    if plan.response_modifier is not None
                    else None
                ),
                "evidence_coverage_retry": True,
            },
        )
        return [
            ValidationIssue(
                code="RECOMMENDATION_COVERAGE_INSUFFICIENT",
                message=(
                    "Broad recommendation has too little independent "
                    "evidence for useful option coverage."
                ),
                task_id=rag_task.task_id,
                recoverable=True,
            )
        ]

    # ========================================================
    # CURRENT INFO GROUNDING
    # ========================================================

    @staticmethod
    def _validate_current_info(
        *,
        plan: ExecutionPlan,
        observations: list[ToolObservation],
        research_evidence: list[EvidenceItem],
    ) -> list[ValidationIssue]:
        if plan.intent != Intent.CURRENT_INFO:
            return []

        web_tasks = [
            task
            for task in plan.subtasks
            if task.tool == ToolName.WEB_SEARCH
        ]

        if not web_tasks:
            return [
                ValidationIssue(
                    code="CURRENT_INFO_WEB_TASK_MISSING",
                    message=(
                        "CURRENT_INFO requires a Web Search task."
                    ),
                    recoverable=False,
                )
            ]

        web_task_ids = {
            task.task_id
            for task in web_tasks
        }
        successful_web = [
            observation
            for observation in observations
            if (
                observation.task_id in web_task_ids
                and observation.tool == ToolName.WEB_SEARCH
                and observation.status == TaskStatus.SUCCESS
            )
        ]

        if not successful_web:
            return [
                ValidationIssue(
                    code="CURRENT_INFO_WEB_FAILED",
                    message=(
                        "CURRENT_INFO Web Search did not complete "
                        "successfully."
                    ),
                    task_id=web_tasks[0].task_id,
                    recoverable=True,
                )
            ]

        web_evidence = [
            item
            for item in research_evidence
            if item.source_type == EvidenceSource.WEB
        ]

        if not web_evidence:
            return [
                ValidationIssue(
                    code="CURRENT_INFO_WEB_EVIDENCE_MISSING",
                    message=(
                        "CURRENT_INFO Web Search produced no "
                        "aggregated Web evidence."
                    ),
                    task_id=successful_web[0].task_id,
                    recoverable=True,
                )
            ]

        has_valid_evidence = any(
            bool(item.url and item.url.strip())
            and bool(item.content.strip())
            for item in web_evidence
        )

        if not has_valid_evidence:
            return [
                ValidationIssue(
                    code="CURRENT_INFO_WEB_EVIDENCE_INVALID",
                    message=(
                        "CURRENT_INFO Web evidence requires a URL "
                        "and non-empty content."
                    ),
                    task_id=successful_web[0].task_id,
                    recoverable=False,
                )
            ]

        current_year = datetime.now(timezone.utc).year

        def explicitly_stale(item: EvidenceItem) -> bool:
            published = item.metadata.get("published_date")
            text = " ".join(
                str(value)
                for value in (published, item.title, item.content)
                if value
            )
            years = [int(value) for value in re.findall(r"\b20\d{2}\b", text)]
            return bool(years) and max(years) < current_year - 1

        if all(explicitly_stale(item) for item in web_evidence):
            return [
                ValidationIssue(
                    code="CURRENT_INFO_EVIDENCE_STALE",
                    message=(
                        "Current information is supported only by "
                        "explicitly old Web evidence."
                    ),
                    task_id=successful_web[0].task_id,
                    recoverable=True,
                )
            ]

        return []

    @staticmethod
    def _validate_entity_specificity(
        *,
        plan: ExecutionPlan,
        research_evidence: list[EvidenceItem],
    ) -> list[ValidationIssue]:
        if plan.intent != Intent.FACTUAL_TRAVEL or len(plan.entities) != 1:
            return []
        if not any(task.tool == ToolName.RAG for task in plan.subtasks):
            return []

        target = normalize_text(plan.entities[0])
        if not target or not research_evidence:
            return []

        specific = [
            item
            for item in research_evidence
            if target in normalize_text(f"{item.title} {item.content}")
        ]
        if specific:
            return []

        logger.warning(
            "RAG evidence deemed insufficient for named entity",
            extra={"entity": plan.entities[0]},
        )
        rag_task = next(
            task for task in plan.subtasks if task.tool == ToolName.RAG
        )
        return [
            ValidationIssue(
                code="ENTITY_EVIDENCE_INSUFFICIENT",
                message=(
                    "Retrieved evidence does not specifically support "
                    f"the named entity: {plan.entities[0]}"
                ),
                task_id=rag_task.task_id,
                recoverable=True,
            )
        ]

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
            ToolName.DISTANCE_MATRIX,
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

        issues.extend(
            self._validate_recommendation_coverage(
                plan=plan,
                research_evidence=research_evidence,
            )
        )

        issues.extend(
            self._validate_current_info(
                plan=plan,
                observations=observations,
                research_evidence=research_evidence,
            )
        )

        issues.extend(
            self._validate_entity_specificity(
                plan=plan,
                research_evidence=research_evidence,
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
