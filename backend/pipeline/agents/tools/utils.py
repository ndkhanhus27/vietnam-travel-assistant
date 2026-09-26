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
