from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def precision_recall_f1(
    *,
    tp: int,
    fp: int,
    fn: int,
) -> dict[str, float]:
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def recall_at_k(
    relevant_ids: Iterable[str],
    retrieved_ids: Sequence[str],
    *,
    k: int,
) -> float:
    relevant = set(relevant_ids)
    if not relevant or k <= 0:
        return 0.0
    return safe_div(len(relevant & set(retrieved_ids[:k])), len(relevant))


def reciprocal_rank(
    relevant_ids: Iterable[str],
    retrieved_ids: Sequence[str],
    *,
    k: int,
) -> float:
    relevant = set(relevant_ids)
    if not relevant or k <= 0:
        return 0.0
    for rank, item_id in enumerate(retrieved_ids[:k], 1):
        if item_id in relevant:
            return 1.0 / rank
    return 0.0


def percentile(values: Iterable[float], percentile_value: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if not 0.0 <= percentile_value <= 100.0:
        raise ValueError("percentile_value must be between 0 and 100")

    position = (len(ordered) - 1) * percentile_value / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
