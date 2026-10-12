import unittest
from datetime import date

from pipeline.agents.executor import ToolExecutor
from pipeline.agents.schemas import (
    ExecutionPlan,
    Intent,
    RetrievalMode,
    SubTask,
    TaskStatus,
    ToolName,
    ToolObservation,
    WeatherRequest,
)
from pipeline.agents.tools.weather import WeatherTool


class MemoryCache:
    def __init__(self):
        self.values = {}
        self.writes = []

    async def get_json(self, key):
        return self.values.get(key)

    async def set_json(self, key, value, *, ttl_seconds):
        self.values[key] = value
        self.writes.append((key, ttl_seconds))
        return True


class Registry:
    def __init__(self, *, status=TaskStatus.SUCCESS):
        self.calls = 0
        self.status = status

    def execute(self, task, **kwargs):
        self.calls += 1
        return ToolObservation(
            task_id=task.task_id,
            tool=task.tool,
            status=self.status,
            data={"weather": [{"temperature_c": 27}]},
            error=None if self.status == TaskStatus.SUCCESS else "provider failed",
            source_count=1 if self.status == TaskStatus.SUCCESS else 0,
        )


def weather_task(task_id="weather-1"):
    return SubTask(
        task_id=task_id,
        description="Check Hue weather",
        tool=ToolName.WEATHER,
        arguments={
            "location": "Huế",
            "mode": "CURRENT",
            "start_offset_days": 0,
            "end_offset_days": 0,
            "original_query": "Huế hôm nay có mưa không?",
        },
    )


def plan(task):
    return ExecutionPlan(
        intent=Intent.WEATHER,
        goal="Check weather",
        entities=["Huế"],
        retrieval_mode=RetrievalMode.TOOL_ONLY,
        subtasks=[task],
    )


class WeatherCacheTest(unittest.IsolatedAsyncioTestCase):
    async def test_successful_weather_is_cached_and_reused_with_current_task_id(self):
        cache = MemoryCache()
        registry = Registry()
        executor = ToolExecutor(registry=registry, cache=cache, weather_cache_ttl_seconds=1800)

        first = await executor.execute(plan(weather_task("weather-1")))
        second = await executor.execute(plan(weather_task("weather-2")))

        self.assertEqual(registry.calls, 1)
        self.assertEqual(first[0].task_id, "weather-1")
        self.assertEqual(second[0].task_id, "weather-2")
        self.assertEqual(cache.writes[0][1], 1800)

    async def test_failed_weather_result_is_not_cached(self):
        cache = MemoryCache()
        registry = Registry(status=TaskStatus.FAILED)
        executor = ToolExecutor(registry=registry, cache=cache)

        await executor.execute(plan(weather_task()))
        await executor.execute(plan(weather_task()))

        self.assertEqual(registry.calls, 2)
        self.assertEqual(cache.writes, [])

    def test_cache_key_normalizes_location_and_changes_with_date_or_range(self):
        request = WeatherRequest.model_validate(weather_task().arguments)
        equivalent = request.model_copy(update={"location": "  HUẾ  "})
        different_range = request.model_copy(update={"end_offset_days": 1})

        first = WeatherTool.cache_key(request, as_of=date(2026, 10, 12))
        self.assertEqual(first, WeatherTool.cache_key(equivalent, as_of=date(2026, 10, 12)))
        self.assertNotEqual(first, WeatherTool.cache_key(request, as_of=date(2026, 10, 13)))
        self.assertNotEqual(first, WeatherTool.cache_key(different_range, as_of=date(2026, 10, 12)))
