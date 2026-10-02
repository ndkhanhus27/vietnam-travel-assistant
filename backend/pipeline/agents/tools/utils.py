from __future__ import annotations

import re
import unicodedata


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
    return cleaned or fallback
