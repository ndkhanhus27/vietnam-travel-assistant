from __future__ import annotations

import hashlib

from pipeline.agents.schemas import (
    EvidenceItem,
    EvidenceSource,
    ToolObservation,
)

from .utils import normalize_text


# ============================================================
# RESEARCH EVIDENCE AGGREGATOR
# ============================================================

class ResearchEvidenceAggregator:
    """
    Aggregate ONLY research evidence:

        - RAG
        - WEB fallback
        - WEB enrichment

    KHÔNG xử lý:

        - WEATHER
        - ROUTING
        - MAP
        - BUDGET / CALCULATION

    Specialized tool observations được giữ riêng
    và truyền trực tiếp sang Reasoner/Synthesizer.

    Responsibilities:

        1. flatten RAG/WEB evidence
        2. deduplicate
        3. balance entities
        4. balance RAG / WEB
        5. limit research context size

    Không dùng LLM.

    Không so sánh trực tiếp:

        CrossEncoder score
        với
        Tavily score

    vì chúng không cùng score scale.
    """

    def __init__(
        self,
        *,
        max_total: int = 8,
        max_per_entity: int = 4,
        max_rag_per_entity: int = 2,
        max_web_per_entity: int = 2,
    ) -> None:

        self.max_total = max_total

        self.max_per_entity = (
            max_per_entity
        )

        self.max_rag_per_entity = (
            max_rag_per_entity
        )

        self.max_web_per_entity = (
            max_web_per_entity
        )

    # ========================================================
    # NORMALIZATION
    # ========================================================

    @staticmethod
    def _normalized_url(
        url: str | None,
    ) -> str:

        if not url:
            return ""

        value = (
            url
            .strip()
            .lower()
        )

        return value.rstrip("/")

    # ========================================================
    # CONTENT FINGERPRINT
    # ========================================================

    @staticmethod
    def _content_fingerprint(
        item: EvidenceItem,
    ) -> str:
        """
        Fingerprint để loại exact/near-exact duplicate
        sau normalization.

        Chỉ lấy 1000 ký tự đầu để tránh hash content
        quá dài không cần thiết.
        """

        normalized = normalize_text(
            item.content[:1000]
        )

        if not normalized:
            return ""

        return hashlib.sha1(
            normalized.encode(
                "utf-8"
            )
        ).hexdigest()[:20]

    # ========================================================
    # DEDUPLICATION
    # ========================================================

    def _deduplicate(
        self,
        evidence: list[EvidenceItem],
    ) -> list[EvidenceItem]:

        output: list[
            EvidenceItem
        ] = []

        seen_ids: set[str] = set()

        seen_urls: set[str] = set()

        seen_contents: set[str] = set()

        for item in evidence:

            # -----------------------------------------------
            # Evidence ID
            # -----------------------------------------------

            if (
                item.evidence_id
                in seen_ids
            ):
                continue

            # -----------------------------------------------
            # URL
            # -----------------------------------------------

            url_key = (
                self._normalized_url(
                    item.url
                )
            )

            if (
                url_key
                and url_key
                in seen_urls
            ):
                continue

            # -----------------------------------------------
            # Content
            # -----------------------------------------------

            content_key = (
                self._content_fingerprint(
                    item
                )
            )

            if (
                content_key
                and content_key
                in seen_contents
            ):
                continue

            # -----------------------------------------------
            # Accept
            # -----------------------------------------------

            seen_ids.add(
                item.evidence_id
            )

            if url_key:

                seen_urls.add(
                    url_key
                )

            if content_key:

                seen_contents.add(
                    content_key
                )

            output.append(
                item
            )

        return output

    # ========================================================
    # SORT INSIDE SAME SOURCE TYPE
    # ========================================================

    @staticmethod
    def _sort_same_source(
        items: list[EvidenceItem],
    ) -> list[EvidenceItem]:
        """
        Chỉ so score giữa evidence cùng source type.

        RAG:
            CrossEncoder scores với nhau.

        WEB:
            Tavily scores với nhau.

        Không compare RAG score với WEB score.
        """

        return sorted(
            items,

            key=lambda item: (
                item.score
                if item.score is not None
                else float("-inf")
            ),

            reverse=True,
        )

    # ========================================================
    # ENTITY KEY
    # ========================================================

    @staticmethod
    def _entity_key(
        item: EvidenceItem,
    ) -> str:

        if not item.entity:

            return "__general__"

        return normalize_text(
            item.entity
        )

    # ========================================================
    # SELECT EVIDENCE FOR ONE ENTITY
    # ========================================================

    def _select_entity_evidence(
        self,
        items: list[EvidenceItem],
    ) -> list[EvidenceItem]:

        # -----------------------------------------------
        # RAG
        # -----------------------------------------------

        rag_items = [
            item
            for item in items
            if (
                item.source_type
                == EvidenceSource.RAG
            )
        ]

        # -----------------------------------------------
        # WEB
        # -----------------------------------------------

        web_items = [
            item
            for item in items
            if (
                item.source_type
                == EvidenceSource.WEB
            )
        ]

        rag_items = (
            self._sort_same_source(
                rag_items
            )
        )

        web_items = (
            self._sort_same_source(
                web_items
            )
        )

        selected: list[
            EvidenceItem
        ] = []

        # -----------------------------------------------
        # Internal RAG backbone
        # -----------------------------------------------

        selected.extend(
            rag_items[
                : self.max_rag_per_entity
            ]
        )

        # -----------------------------------------------
        # External web diversity
        # -----------------------------------------------

        selected.extend(
            web_items[
                : self.max_web_per_entity
            ]
        )

        # -----------------------------------------------
        # Nếu một source thiếu evidence,
        # source còn lại có thể fill slot.
        # -----------------------------------------------

        if (
            len(selected)
            < self.max_per_entity
        ):

            selected_ids = {
                item.evidence_id
                for item in selected
            }

            leftovers = [
                item
                for item in (
                    rag_items
                    + web_items
                )
                if (
                    item.evidence_id
                    not in selected_ids
                )
            ]

            remaining = (
                self.max_per_entity
                - len(selected)
            )

            selected.extend(
                leftovers[
                    :remaining
                ]
            )

        return selected[
            : self.max_per_entity
        ]

    # ========================================================
    # PUBLIC
    # ========================================================

    def aggregate(
        self,
        observations: list[
            ToolObservation
        ],
    ) -> list[EvidenceItem]:
        """
        Aggregate research evidence từ ToolObservations.

        Weather / Routing / Map / Budget evidence
        nếu xuất hiện trong observations
        sẽ bị bỏ qua ở đây.

        Chúng KHÔNG bị mất:
        original observations vẫn còn nguyên.
        """

        # ====================================================
        # FLATTEN ONLY RAG + WEB
        # ====================================================

        raw_evidence: list[
            EvidenceItem
        ] = []

        for observation in observations:

            for item in (
                observation.evidence
            ):

                if (
                    item.source_type
                    not in {
                        EvidenceSource.RAG,
                        EvidenceSource.WEB,
                    }
                ):
                    continue

                raw_evidence.append(
                    item
                )

        if not raw_evidence:
            return []

        # ====================================================
        # DEDUPLICATE
        # ====================================================

        clean = (
            self._deduplicate(
                raw_evidence
            )
        )

        # ====================================================
        # GROUP BY ENTITY
        # ====================================================

        groups: dict[
            str,
            list[EvidenceItem],
        ] = {}

        entity_order: list[str] = []

        for item in clean:

            key = (
                self._entity_key(
                    item
                )
            )

            if key not in groups:

                groups[key] = []

                entity_order.append(
                    key
                )

            groups[key].append(
                item
            )

        # ====================================================
        # SELECT PER ENTITY
        # ====================================================

        per_entity: dict[
            str,
            list[EvidenceItem],
        ] = {}

        for key in entity_order:

            per_entity[key] = (
                self
                ._select_entity_evidence(
                    groups[key]
                )
            )

        # ====================================================
        # ENTITY-BALANCED ROUND ROBIN
        # ====================================================

        result: list[
            EvidenceItem
        ] = []

        positions = {
            key: 0
            for key in entity_order
        }

        while (
            len(result)
            < self.max_total
        ):

            added_any = False

            for key in entity_order:

                position = (
                    positions[key]
                )

                items = (
                    per_entity[key]
                )

                if (
                    position
                    >= len(items)
                ):
                    continue

                result.append(
                    items[position]
                )

                positions[key] += 1

                added_any = True

                if (
                    len(result)
                    >= self.max_total
                ):
                    break

            if not added_any:
                break

        return result


# ============================================================
# EVIDENCE AGGREGATOR
# ============================================================

class EvidenceAggregator:
    """
    Gom evidence từ nhiều ToolObservation.

    Trách nhiệm:

    1. flatten evidence
    2. deduplicate
    3. giữ diversity giữa entities
    4. giữ diversity giữa RAG / WEB
    5. giới hạn số evidence trước khi đưa sang Reasoner /
       Synthesizer

    Không dùng LLM.

    Không so sánh trực tiếp score giữa các provider vì:

        RAG CrossEncoder score
        !=
        Tavily score

    Hai score không cùng calibration.
    """

    def __init__(
        self,
        *,
        max_total: int = 8,
        max_per_entity: int = 4,
        max_rag_per_entity: int = 2,
        max_web_per_entity: int = 2,
    ) -> None:

        self.max_total = max_total

        self.max_per_entity = (
            max_per_entity
        )

        self.max_rag_per_entity = (
            max_rag_per_entity
        )

        self.max_web_per_entity = (
            max_web_per_entity
        )

    # ========================================================
    # NORMALIZATION
    # ========================================================

    @staticmethod
    def _normalized_url(
        url: str | None,
    ) -> str:

        if not url:
            return ""

        value = url.strip().lower()

        # Bỏ trailing slash đơn giản.
        return value.rstrip("/")

    @staticmethod
    def _content_fingerprint(
        item: EvidenceItem,
    ) -> str:
        """
        Fingerprint phục vụ dedupe.

        Không dùng toàn bộ content để giảm chi phí.
        """

        normalized = normalize_text(
            item.content[:1000]
        )

        digest = hashlib.sha1(
            normalized.encode(
                "utf-8"
            )
        ).hexdigest()[:20]

        return digest

    # ========================================================
    # DEDUPLICATION
    # ========================================================

    def _deduplicate(
        self,
        evidence: list[EvidenceItem],
    ) -> list[EvidenceItem]:

        output: list[
            EvidenceItem
        ] = []

        seen_ids: set[str] = set()

        seen_urls: set[str] = set()

        seen_content: set[str] = set()

        for item in evidence:

            # -----------------------------------------------
            # evidence_id
            # -----------------------------------------------

            if (
                item.evidence_id
                in seen_ids
            ):
                continue

            # -----------------------------------------------
            # URL
            # -----------------------------------------------

            url_key = (
                self._normalized_url(
                    item.url
                )
            )

            if (
                url_key
                and url_key in seen_urls
            ):
                continue

            # -----------------------------------------------
            # Content fingerprint
            # -----------------------------------------------

            content_key = (
                self._content_fingerprint(
                    item
                )
            )

            if (
                content_key
                and content_key
                in seen_content
            ):
                continue

            seen_ids.add(
                item.evidence_id
            )

            if url_key:
                seen_urls.add(
                    url_key
                )

            if content_key:
                seen_content.add(
                    content_key
                )

            output.append(
                item
            )

        return output

    # ========================================================
    # SCORE ORDERING WITHIN ONE SOURCE
    # ========================================================

    @staticmethod
    def _sort_same_source(
        items: list[EvidenceItem],
    ) -> list[EvidenceItem]:
        """
        Score chỉ dùng để order evidence cùng loại/provider.

        Không dùng Tavily score để so trực tiếp
        với CrossEncoder score.
        """

        return sorted(
            items,
            key=lambda item: (
                item.score
                if item.score is not None
                else float("-inf")
            ),
            reverse=True,
        )

    # ========================================================
    # ENTITY KEY
    # ========================================================

    @staticmethod
    def _entity_key(
        item: EvidenceItem,
    ) -> str:

        if not item.entity:
            return "__general__"

        return normalize_text(
            item.entity
        )

    # ========================================================
    # SELECT ONE ENTITY
    # ========================================================

    def _select_entity_evidence(
        self,
        items: list[EvidenceItem],
    ) -> list[EvidenceItem]:

        rag_items = [
            item
            for item in items
            if (
                item.source_type
                == EvidenceSource.RAG
            )
        ]

        web_items = [
            item
            for item in items
            if (
                item.source_type
                == EvidenceSource.WEB
            )
        ]

        other_items = [
            item
            for item in items
            if item.source_type
            not in {
                EvidenceSource.RAG,
                EvidenceSource.WEB,
            }
        ]

        rag_items = (
            self._sort_same_source(
                rag_items
            )
        )

        web_items = (
            self._sort_same_source(
                web_items
            )
        )

        # Other evidence như weather/routing:
        # giữ nguyên order vì score semantics
        # có thể khác hoàn toàn.
        selected: list[
            EvidenceItem
        ] = []

        # -----------------------------------------------
        # RAG backbone
        # -----------------------------------------------

        selected.extend(
            rag_items[
                : self.max_rag_per_entity
            ]
        )

        # -----------------------------------------------
        # Web diversity
        # -----------------------------------------------

        selected.extend(
            web_items[
                : self.max_web_per_entity
            ]
        )

        # -----------------------------------------------
        # Structured/specialized tools
        # -----------------------------------------------

        remaining = (
            self.max_per_entity
            - len(selected)
        )

        if remaining > 0:

            selected.extend(
                other_items[
                    :remaining
                ]
            )

        # -----------------------------------------------
        # Nếu còn slot mà một source không đủ,
        # fill từ source còn lại.
        # -----------------------------------------------

        if (
            len(selected)
            < self.max_per_entity
        ):

            selected_ids = {
                item.evidence_id
                for item in selected
            }

            leftovers = [
                item
                for item in (
                    rag_items
                    + web_items
                    + other_items
                )
                if (
                    item.evidence_id
                    not in selected_ids
                )
            ]

            remaining = (
                self.max_per_entity
                - len(selected)
            )

            selected.extend(
                leftovers[:remaining]
            )

        return selected[
            : self.max_per_entity
        ]

    # ========================================================
    # PUBLIC
    # ========================================================

    def aggregate(
        self,
        observations: list[
            ToolObservation
        ],
    ) -> list[EvidenceItem]:

        # ====================================================
        # FLATTEN
        # ====================================================

        raw_evidence: list[
            EvidenceItem
        ] = []

        for observation in observations:

            raw_evidence.extend(
                observation.evidence
            )

        if not raw_evidence:
            return []

        # ====================================================
        # DEDUPE
        # ====================================================

        clean = self._deduplicate(
            raw_evidence
        )

        # ====================================================
        # GROUP BY ENTITY
        # ====================================================

        groups: dict[
            str,
            list[EvidenceItem],
        ] = {}

        entity_order: list[str] = []

        for item in clean:

            key = self._entity_key(
                item
            )

            if key not in groups:

                groups[key] = []

                entity_order.append(
                    key
                )

            groups[key].append(
                item
            )

        # ====================================================
        # ENTITY-BALANCED FIRST PASS
        # ====================================================

        per_entity: dict[
            str,
            list[EvidenceItem],
        ] = {}

        for key in entity_order:

            per_entity[key] = (
                self._select_entity_evidence(
                    groups[key]
                )
            )

        result: list[
            EvidenceItem
        ] = []

        positions = {
            key: 0
            for key in entity_order
        }

        # Round-robin:
        #
        # Sa Pa evidence 1
        # Đà Lạt evidence 1
        # Sa Pa evidence 2
        # Đà Lạt evidence 2
        #
        # thay vì lấy hết Sa Pa trước.
        while (
            len(result)
            < self.max_total
        ):

            added_any = False

            for key in entity_order:

                position = (
                    positions[key]
                )

                items = (
                    per_entity[key]
                )

                if position >= len(items):
                    continue

                result.append(
                    items[position]
                )

                positions[key] += 1

                added_any = True

                if (
                    len(result)
                    >= self.max_total
                ):
                    break

            if not added_any:
                break

        return result
