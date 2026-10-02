from __future__ import annotations

import hashlib

from tavily import TavilyClient

from app.core.config import settings
from pipeline.agents.schemas import (
    EvidenceItem,
    EvidenceSource,
)

from .utils import normalize_text, sanitize_source_title, source_quality_rank


# ============================================================
# WEB SEARCH TOOL
# ============================================================

class WebSearchTool:
    """
    Tavily web retrieval adapter.

    Nhiệm vụ duy nhất:

        query
          ↓
        Tavily
          ↓
        EvidenceItem[]

    Không:
    - gọi Gemini
    - synthesize answer
    - quyết định final response
    """

    def __init__(self) -> None:

        if not settings.tavily_api_key:
            raise RuntimeError(
                "TAVILY_API_KEY chưa được cấu hình."
            )

        self.client = TavilyClient(
            api_key=settings.tavily_api_key
        )

    # ========================================================
    # EVIDENCE ID
    # ========================================================

    @staticmethod
    def _evidence_id(
        url: str,
    ) -> str:
        """
        Tạo deterministic evidence ID từ URL.

        Không dùng built-in hash()
        vì Python hash có thể khác giữa process.
        """

        digest = hashlib.sha1(
            url.encode(
                "utf-8"
            )
        ).hexdigest()[:16]

        return f"web_{digest}"

    # ========================================================
    # ENTITY COVERAGE
    # ========================================================

    @staticmethod
    def _matches_entity(
        *,
        entity: str,
        title: str,
        content: str,
    ) -> bool:
        """
        Basic deterministic web coverage filter.

        Nếu search dành riêng cho một entity thì
        entity phải thực sự xuất hiện trong
        title hoặc returned content.

        Đây chưa phải semantic web validator.
        """

        target = normalize_text(
            entity
        )

        if not target:
            return True

        combined = normalize_text(
            f"{title} {content}"
        )

        return target in combined

    # ========================================================
    # SEARCH
    # ========================================================

    def search(
        self,
        *,
        query: str,
        entity: str | None = None,
        purpose: str = "direct",
    ) -> list[EvidenceItem]:
        query = query.strip()

        if not query:
            return []

        response = self.client.search(
            query=query,

            search_depth=(
                settings.web_search_depth
            ),

            max_results=(
                settings.web_search_max_results
            ),

            chunks_per_source=(
                settings
                .web_search_chunks_per_source
            ),

            include_answer=False,

            include_raw_content=False,
        )

        results = response.get(
            "results",
            [],
        )

        evidence: list[
            EvidenceItem
        ] = []

        seen_urls: set[str] = set()

        for item in results:

            title = str(
                item.get(
                    "title",
                    "",
                )
            ).strip()

            url = str(
                item.get(
                    "url",
                    "",
                )
            ).strip()

            content = str(
                item.get(
                    "content",
                    "",
                )
            ).strip()

            # ------------------------------------------------
            # Basic validity
            # ------------------------------------------------

            if not url:
                continue

            if not content:
                continue

            # ------------------------------------------------
            # Entity coverage
            # ------------------------------------------------

            if (
                entity
                and not self._matches_entity(
                    entity=entity,
                    title=title,
                    content=content,
                )
            ):
                continue

            # ------------------------------------------------
            # URL deduplication
            # ------------------------------------------------

            if url in seen_urls:
                continue

            seen_urls.add(
                url
            )

            # ------------------------------------------------
            # Tavily score
            # ------------------------------------------------

            raw_score = item.get(
                "score"
            )

            score = (
                float(raw_score)
                if raw_score is not None
                else None
            )

            # ------------------------------------------------
            # Unified evidence
            # ------------------------------------------------

            evidence.append(
                EvidenceItem(
                    evidence_id=(
                        self._evidence_id(
                            url
                        )
                    ),

                    source_type=(
                        EvidenceSource.WEB
                    ),

                    title=(
                        sanitize_source_title(
                            title,
                            fallback=url,
                        )
                    ),

                    content=content,

                    url=url,

                    entity=entity,

                    score=score,

                    metadata={
                        "provider": "tavily",
                        "search_query": query,
                        "entity": entity,
                        "purpose": purpose,
                        "published_date": item.get("published_date"),
                        "source_quality_rank": source_quality_rank(url),
                    },
                )
            )

        return evidence
