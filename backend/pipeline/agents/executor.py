from __future__ import annotations

import asyncio

from pipeline.agents.schemas import (
    ExecutionPlan,
    SubTask,
    TaskStatus,
    ToolObservation,
)

from pipeline.agents.tools import (
    ToolRegistry,
)


# ============================================================
# TOOL EXECUTOR
# ============================================================


class ToolExecutor:
    """
    Execute ExecutionPlan theo dependency DAG.

    Responsibilities:

        1. validate task dependency graph
        2. tìm các task ready
        3. chạy các task độc lập song song
        4. chờ dependency trước khi chạy dependent task
        5. skip task nếu dependency của nó failed/skipped
        6. trả về ToolObservation theo thứ tự subtasks ban đầu

    Không:

        - gọi Planner
        - aggregate research evidence
        - reasoning
        - synthesis
        - retry
        - LangGraph orchestration

    ToolRegistry hiện synchronous nên execution song song
    được thực hiện bằng asyncio.to_thread().
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        max_concurrency: int = 4,
    ) -> None:

        if max_concurrency <= 0:
            raise ValueError(
                "max_concurrency must be > 0"
            )

        self.registry = (
            registry
            if registry is not None
            else ToolRegistry()
        )

        self.max_concurrency = (
            max_concurrency
        )

    # ========================================================
    # GRAPH VALIDATION
    # ========================================================

    @staticmethod
    def _validate_plan(
        plan: ExecutionPlan,
    ) -> None:
        """
        Validate structural dependency errors trước execution.

        Checks:

            - duplicate task_id
            - dependency không tồn tại
            - task depend chính nó

        Cycle được phát hiện trong execution loop.
        """

        task_ids = [
            task.task_id
            for task in plan.subtasks
        ]

        # ----------------------------------------------------
        # DUPLICATE TASK IDs
        # ----------------------------------------------------

        if len(task_ids) != len(
            set(task_ids)
        ):

            raise ValueError(
                "ExecutionPlan contains "
                "duplicate task_id."
            )

        known_ids = set(
            task_ids
        )

        # ----------------------------------------------------
        # DEPENDENCY VALIDATION
        # ----------------------------------------------------

        for task in plan.subtasks:

            for dependency_id in (
                task.depends_on
            ):

                if (
                    dependency_id
                    == task.task_id
                ):

                    raise ValueError(
                        f"Task "
                        f"{task.task_id!r} "
                        "cannot depend on itself."
                    )

                if (
                    dependency_id
                    not in known_ids
                ):

                    raise ValueError(
                        f"Task "
                        f"{task.task_id!r} "
                        "depends on unknown task "
                        f"{dependency_id!r}."
                    )

    # ========================================================
    # DEPENDENCY HELPERS
    # ========================================================

    @staticmethod
    def _dependencies_finished(
        task: SubTask,
        completed: dict[
            str,
            ToolObservation,
        ],
    ) -> bool:
        """
        True khi toàn bộ dependencies đã terminal.
        """

        return all(
            dependency_id
            in completed
            for dependency_id
            in task.depends_on
        )

    @staticmethod
    def _failed_dependencies(
        task: SubTask,
        completed: dict[
            str,
            ToolObservation,
        ],
    ) -> list[str]:
        """
        Dependencies không SUCCESS.

        Bao gồm:

            FAILED
            SKIPPED
        """

        failed: list[str] = []

        for dependency_id in (
            task.depends_on
        ):

            observation = (
                completed.get(
                    dependency_id
                )
            )

            if observation is None:
                continue

            if (
                observation.status
                != TaskStatus.SUCCESS
            ):

                failed.append(
                    dependency_id
                )

        return failed

    # ========================================================
    # SKIPPED OBSERVATION
    # ========================================================

    @staticmethod
    def _dependency_skipped(
        task: SubTask,
        failed_dependencies: list[str],
    ) -> ToolObservation:

        return ToolObservation(
            task_id=task.task_id,

            tool=task.tool,

            status=TaskStatus.SKIPPED,

            data={
                "error_code": (
                    "DEPENDENCY_FAILED"
                ),

                "failed_dependencies": (
                    failed_dependencies
                ),
            },

            evidence=[],

            coverage=None,

            error=(
                "Task skipped because "
                "one or more dependencies "
                "did not complete successfully: "
                + ", ".join(
                    failed_dependencies
                )
            ),

            source_count=0,
        )

    # ========================================================
    # EXECUTE ONE TASK
    # ========================================================

    async def _execute_task(
        self,
        *,
        task: SubTask,
        plan: ExecutionPlan,
        semaphore: asyncio.Semaphore,
    ) -> ToolObservation:
        """
        Execute one synchronous ToolRegistry call
        in worker thread.

        Semaphore giới hạn số external/tool calls
        chạy đồng thời.
        """

        async with semaphore:

            observation = (
                await asyncio.to_thread(
                    self.registry.execute,
                    task,
                    research_depth=(
                        plan.research_depth
                    ),
                )
            )

            return observation

    # ========================================================
    # EXECUTE ONE WAVE
    # ========================================================

    async def _execute_wave(
        self,
        *,
        tasks: list[SubTask],
        plan: ExecutionPlan,
        semaphore: asyncio.Semaphore,
    ) -> list[
        tuple[
            str,
            ToolObservation,
        ]
    ]:
        """
        Các task trong cùng wave không còn dependency
        chưa hoàn thành, nên có thể chạy concurrent.
        """

        coroutines = [
            self._execute_task(
                task=task,
                plan=plan,
                semaphore=semaphore,
            )
            for task in tasks
        ]

        observations = (
            await asyncio.gather(
                *coroutines
            )
        )

        return [
            (
                task.task_id,
                observation,
            )
            for task, observation
            in zip(
                tasks,
                observations,
                strict=True,
            )
        ]

    # ========================================================
    # PUBLIC ASYNC API
    # ========================================================

    async def execute(
        self,
        plan: ExecutionPlan,
    ) -> list[ToolObservation]:
        """
        Execute toàn bộ ExecutionPlan.

        Return order luôn theo thứ tự plan.subtasks,
        không theo thứ tự task hoàn thành.
        """

        self._validate_plan(
            plan
        )

        if not plan.subtasks:
            return []

        # task_id -> task
        pending: dict[
            str,
            SubTask,
        ] = {
            task.task_id: task
            for task in plan.subtasks
        }

        # task_id -> result
        completed: dict[
            str,
            ToolObservation,
        ] = {}

        semaphore = (
            asyncio.Semaphore(
                self.max_concurrency
            )
        )

        # ====================================================
        # DAG EXECUTION LOOP
        # ====================================================

        while pending:

            ready_tasks: list[
                SubTask
            ] = []

            # =================================================
            # FIND READY TASKS
            # =================================================

            for task in list(
                pending.values()
            ):

                if (
                    self._dependencies_finished(
                        task,
                        completed,
                    )
                ):

                    ready_tasks.append(
                        task
                    )

            # =================================================
            # NO READY TASK = CYCLE
            # =================================================

            if not ready_tasks:

                remaining_ids = list(
                    pending.keys()
                )

                raise ValueError(
                    "Dependency cycle detected "
                    "in ExecutionPlan. "
                    "Remaining tasks: "
                    f"{remaining_ids}"
                )

            # =================================================
            # FIRST: SKIP TASKS WITH FAILED DEPENDENCIES
            # =================================================

            runnable_tasks: list[
                SubTask
            ] = []

            for task in ready_tasks:

                failed_dependencies = (
                    self._failed_dependencies(
                        task,
                        completed,
                    )
                )

                if failed_dependencies:

                    completed[
                        task.task_id
                    ] = (
                        self._dependency_skipped(
                            task,
                            failed_dependencies,
                        )
                    )

                    pending.pop(
                        task.task_id,
                        None,
                    )

                    continue

                runnable_tasks.append(
                    task
                )

            # =================================================
            # EXECUTE RUNNABLE TASKS IN PARALLEL
            # =================================================

            if runnable_tasks:

                wave_results = (
                    await self._execute_wave(
                        tasks=runnable_tasks,
                        plan=plan,
                        semaphore=semaphore,
                    )
                )

                for (
                    task_id,
                    observation,
                ) in wave_results:

                    completed[
                        task_id
                    ] = observation

                    pending.pop(
                        task_id,
                        None,
                    )

        # ====================================================
        # STABLE OUTPUT ORDER
        # ====================================================

        return [
            completed[
                task.task_id
            ]
            for task in plan.subtasks
        ]

    # ========================================================
    # SYNC CONVENIENCE API
    # ========================================================

    def execute_sync(
        self,
        plan: ExecutionPlan,
    ) -> list[ToolObservation]:
        """
        Convenience method cho CLI/tests synchronous.

        Production FastAPI/LangGraph async flow sau này
        nên gọi:

            await executor.execute(plan)

        thay vì execute_sync().
        """

        return asyncio.run(
            self.execute(
                plan
            )
        )