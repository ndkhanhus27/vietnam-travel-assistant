from __future__ import annotations

from typing import Any

from .budget import BudgetTool
from .map_location import MapLocationTool
from .routing import RoutingTool
from .registry import ToolRegistry
from .research_evidence import (
    EvidenceAggregator,
    ResearchEvidenceAggregator,
)
from .weather import WeatherTool
from .web import WebSearchTool
from .utils import normalize_text


def __getattr__(name: str) -> Any:
    if name == "TravelKnowledgeTool":
        from .knowledge import TravelKnowledgeTool

        return TravelKnowledgeTool

    if name in {"main", "parse_args"}:
        from .cli import main, parse_args

        return {
            "main": main,
            "parse_args": parse_args,
        }[name]

    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )

__all__ = [
    "WebSearchTool",
    "TravelKnowledgeTool",
    "WeatherTool",
    "BudgetTool",
    "MapLocationTool",
    "RoutingTool",
    "ToolRegistry",
    "ResearchEvidenceAggregator",
    "EvidenceAggregator",
    "normalize_text",
    "parse_args",
    "main",
]
