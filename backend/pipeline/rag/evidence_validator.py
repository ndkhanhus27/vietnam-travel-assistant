from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.rag.reranker import RerankedChunk


@dataclass(frozen=True)
class EvidenceValidation:
    valid: bool
    issues: list[str]


@dataclass(frozen=True)
class CitationValidation:
    valid: bool
    citations: list[str]
    issues: list[str]


class EvidenceValidator:
    """
    Validator deterministic.

    Không dùng LLM.

    Kiểm tra:
    - có evidence hay không
    - content không rỗng
    - source tồn tại
    - duplicate point
    - citation Gemini có hợp lệ không
    """

    @staticmethod
    def validate_evidence(
        evidence: list[RerankedChunk],
    ) -> EvidenceValidation:
        issues: list[str] = []

        if not evidence:
            return EvidenceValidation(
                valid=False,
                issues=["Không có evidence."],
            )

        seen_point_ids: set[str] = set()
        useful_count = 0

        for index, item in enumerate(evidence, start=1):
            if item.point_id in seen_point_ids:
                issues.append(f"Evidence {index} bị duplicate.")

            seen_point_ids.add(item.point_id)

            content = (item.content or "").strip()

            if len(content) < 30:
                issues.append(f"Evidence {index} có content quá ngắn.")
            else:
                useful_count += 1

            if not item.title.strip():
                issues.append(f"Evidence {index} thiếu title.")

            if not item.source_url.strip():
                issues.append(f"Evidence {index} thiếu source_url.")

        if useful_count == 0:
            issues.append("Không có evidence đủ nội dung.")

        return EvidenceValidation(
            valid=useful_count > 0,
            issues=issues,
        )

    @staticmethod
    def validate_citations(
        *,
        answer: str,
        source_count: int,
    ) -> CitationValidation:
        matches = re.findall(r"\[S(\d+)\]", answer)
        citations = [f"S{number}" for number in matches]

        issues: list[str] = []

        for number_text in matches:
            number = int(number_text)

            if number < 1 or number > source_count:
                issues.append(f"Citation S{number} không tồn tại.")

        if source_count > 0 and not citations:
            issues.append("Câu trả lời không có citation.")

        return CitationValidation(
            valid=len(issues) == 0,
            citations=citations,
            issues=issues,
        )
