import re
import unicodedata

from pipeline.entity.schemas import (
    ExtractedEntityCandidate,
)


def normalize_entity_name(
    name: str,
) -> str:
    """
    Chuẩn hóa tên để deduplicate.

    Không bỏ dấu tiếng Việt.
    """

    value = unicodedata.normalize(
        "NFC",
        name,
    )

    value = value.strip()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    value = value.strip(
        ".,;:!?()[]{}\"'“”‘’"
    )

    return value.casefold()


def _safe_confidence(
    value: float,
) -> float:
    """
    Defensive clamp.

    Schema + prompt đã yêu cầu 0..1,
    nhưng application vẫn tự bảo vệ.
    """

    return max(
        0.0,
        min(float(value), 1.0),
    )


def merge_candidates(
    candidates: list[
        ExtractedEntityCandidate
    ],
) -> list[
        ExtractedEntityCandidate
    ]:
    """
    Deduplicate theo:

        normalized_name
        +
        entity_type

    Nếu trùng:
    - primary thắng mention
    - confidence cao hơn thắng
    """

    merged: dict[
        tuple[str, str],
        ExtractedEntityCandidate,
    ] = {}

    for candidate in candidates:
        normalized_name = (
            normalize_entity_name(
                candidate.name
            )
        )

        if not normalized_name:
            continue

        clean_candidate = (
            ExtractedEntityCandidate(
                name=(
                    candidate.name.strip()
                ),
                entity_type=(
                    candidate.entity_type
                ),
                role=(
                    candidate.role
                ),
                mention_text=(
                    candidate
                    .mention_text
                    .strip()
                ),
                confidence=(
                    _safe_confidence(
                        candidate.confidence
                    )
                ),
            )
        )

        key = (
            normalized_name,
            clean_candidate.entity_type,
        )

        existing = merged.get(
            key
        )

        if existing is None:
            merged[key] = (
                clean_candidate
            )

            continue

        # Primary luôn ưu tiên.
        if (
            clean_candidate.role
            == "primary"
            and existing.role
            != "primary"
        ):
            merged[key] = (
                clean_candidate
            )

            continue

        # Cùng role:
        # confidence cao hơn thắng.
        if (
            clean_candidate.role
            == existing.role
            and clean_candidate.confidence
            > existing.confidence
        ):
            merged[key] = (
                clean_candidate
            )

    return list(
        merged.values()
    )