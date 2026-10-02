from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(
    value: str,
) -> str:
    """
    Conservative text normalization.

    Dùng cho entity coverage checking.

    Hiện tại:
    - Unicode NFC
    - case-insensitive
    - normalize whitespace

    Không dùng fuzzy matching.
    Không bỏ dấu tiếng Việt.
    """

    value = unicodedata.normalize(
        "NFC",
        value,
    )

    value = value.casefold()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def sanitize_source_title(value: str, *, fallback: str) -> str:
    """Remove common scraped asset labels from user-facing source titles."""
    title = " ".join(str(value or "").split())
    if not title:
        return fallback

    parts = [
        part
        for part in title.split()
        if part.casefold() != "svg" and not part.casefold().endswith(".svg")
    ]
    cleaned = " ".join(parts).strip(" |-_")
    cleaned = re.sub(r"(?:[\s|_-]*\.?svg)+$", "", cleaned, flags=re.IGNORECASE)
    return cleaned or fallback


def format_tool_data_for_presentation(value: Any, *, key: str = "") -> Any:
    """Return a display-oriented copy without mutating provider data."""

    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for child_key, child_value in value.items():
            if child_key == "precipitation_probability" and isinstance(
                child_value, (int, float)
            ):
                probability = float(child_value)
                if 0 <= probability <= 1:
                    probability *= 100
                output["precipitation_probability_percent"] = round(probability)
                continue
            output[child_key] = format_tool_data_for_presentation(
                child_value,
                key=child_key,
            )
        return output

    if isinstance(value, list):
        return [format_tool_data_for_presentation(item, key=key) for item in value]

    if isinstance(value, float):
        if key.endswith("_c") or key.endswith("_percent"):
            return round(value)
        if key.endswith("_mm"):
            return round(value, 1)
        if key in {"wind_speed", "wind_speed_mps"}:
            return round(value, 1)
        return round(value, 2)

    return value


def source_quality_rank(url: str | None) -> int:
    """Small, explainable authority prior; relevance score still breaks ties."""

    host = (urlsplit(url or "").hostname or "").casefold()
    if host.endswith(".gov.vn") or host in {"vietnam.travel", "www.vietnam.travel"}:
        return 6
    if host.endswith(".edu.vn") or host.endswith(".org.vn"):
        return 5
    social_hosts = (
        "tiktok.com",
        "facebook.com",
        "instagram.com",
        "reddit.com",
        "youtube.com",
        "x.com",
        "twitter.com",
    )
    if any(host == item or host.endswith(f".{item}") for item in social_hosts):
        return 1
    return 3
