import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from heapq import heappop, heappush
from itertools import count
from typing import Any
from urllib.parse import quote

import httpx

from .base_crawler import BaseCrawler, CrawledRawDocument


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CategoryCursor:
    """Một category và cursor phân trang đang chờ được BFS xử lý."""

    title: str
    depth: int
    continuation: dict[str, Any] | None = None


class WikivoyageCrawler(BaseCrawler):
    """
    Thu thập nguyên trạng Wikitext từ MediaWiki API.

    Discovery chỉ đi theo CATEGORY TREE:

        category seed (depth 0)
            -> subcategory (depth 1)
                -> subcategory (depth 2)
                    -> ...

    Không follow internal article links.

    Với cấu hình Việt Nam nên dùng:

        category_titles = ("Thể loại:Việt Nam",)

    và điều chỉnh ``max_category_depth`` để quyết định crawler
    được đi sâu bao nhiêu tầng category.

    Crawler chỉ discovery + fetch raw Wikitext.
    ETL chịu trách nhiệm:
    - extract plain text
    - phân loại entity
    - xác định region/country
    - loại noise
    - quality checking
    """

    _REQUEST_DELAY_SECONDS = 0.2
    _MAX_RETRIES = 5

    # Số article fetch revision trong một request.
    _PAGE_BATCH_SIZE = 20

    async def crawl(
        self,
        limit: int = 1_000,
    ) -> list[CrawledRawDocument]:
        """
        Crawl tối đa ``limit`` raw documents.

        Flow:

        category BFS theo ``max_category_depth``
            ↓
        candidate article pages
            ↓
        fetch raw revisions
            ↓
        tối đa ``limit`` documents
        """

        if limit <= 0:
            return []

        headers = {
            "User-Agent": (
                "VietnamTravelAdvisor/1.0 "
                "(educational RAG crawler)"
            ),
            "Accept": "application/json",
        }

        documents: list[CrawledRawDocument] = []

        # Discovery thêm khoảng 10% candidate.
        #
        # Ví dụ limit=1000:
        #
        #   discover ~1100 candidates
        #   fetch được 1080 valid
        #   return 1000
        #
        # Việc này giúp bù cho:
        # - missing page
        # - page không revision
        # - payload lỗi
        # - request riêng lẻ thất bại
        candidate_limit = max(
            limit,
            int(limit * 1.10),
        )

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers=headers,
            follow_redirects=True,
        ) as client:

            # ---------------------------------------------------------
            # STEP 1: CATEGORY BFS
            # ---------------------------------------------------------

            pages = await self._list_pages(
                client,
                limit=candidate_limit,
                category_titles=self.config.category_titles,
                max_depth=self.config.max_category_depth,
            )

            logger.info(
                "wikivoyage_category_discovery "
                "requested=%d candidate_limit=%d pages=%d",
                limit,
                candidate_limit,
                len(pages),
            )

            # ---------------------------------------------------------
            # STEP 2: FETCH RAW WIKITEXT
            # ---------------------------------------------------------

            for page_batch in self._batches(
                pages,
                self._PAGE_BATCH_SIZE,
            ):
                if len(documents) >= limit:
                    break

                fetched = await self._fetch_page_batch_resilient(
                    client,
                    page_batch,
                )

                documents.extend(fetched)

        # Có thể discovery/fetch dư để bù lỗi.
        documents = documents[:limit]

        logger.info(
            "wikivoyage_crawl_completed "
            "requested=%d candidates=%d fetched=%d",
            limit,
            len(pages),
            len(documents),
        )

        return documents

    # ================================================================
    # COMMON
    # ================================================================

    @staticmethod
    def _batches(
        items: list[dict[str, Any]],
        size: int,
    ) -> list[list[dict[str, Any]]]:
        return [
            items[index : index + size]
            for index in range(0, len(items), size)
        ]

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        """
        Gọi MediaWiki API.

        Retry khi:
        - HTTP 429
        - HTTP 5xx
        - network/request error
        """

        for attempt in range(self._MAX_RETRIES):
            try:
                response = await client.get(
                    self.config.api_url,
                    params=params,
                )

                response.raise_for_status()

                data = response.json()

                if not isinstance(data, dict):
                    raise ValueError(
                        "MediaWiki API không trả về JSON object"
                    )

                # Rate-limit nhẹ, tránh spam API.
                await asyncio.sleep(
                    self._REQUEST_DELAY_SECONDS
                )

                return data

            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code

                retryable = (
                    status_code == 429
                    or 500 <= status_code < 600
                )

                if (
                    not retryable
                    or attempt == self._MAX_RETRIES - 1
                ):
                    logger.warning(
                        "wikivoyage_http_error "
                        "status=%s url=%s timestamp=%s",
                        status_code,
                        exc.request.url,
                        datetime.now(UTC).isoformat(),
                    )
                    raise

                retry_after = exc.response.headers.get(
                    "Retry-After"
                )

                try:
                    wait_seconds = (
                        float(retry_after)
                        if retry_after
                        else 2**attempt
                    )
                except ValueError:
                    wait_seconds = 2**attempt

                logger.info(
                    "wikivoyage_retry "
                    "status=%s attempt=%s/%s wait=%ss",
                    status_code,
                    attempt + 1,
                    self._MAX_RETRIES,
                    wait_seconds,
                )

                await asyncio.sleep(wait_seconds)

            except httpx.RequestError as exc:
                if attempt == self._MAX_RETRIES - 1:
                    logger.warning(
                        "wikivoyage_request_error "
                        "url=%s error=%s timestamp=%s",
                        self.config.api_url,
                        exc,
                        datetime.now(UTC).isoformat(),
                    )
                    raise

                wait_seconds = 2**attempt

                logger.info(
                    "wikivoyage_request_retry "
                    "attempt=%s/%s wait=%ss",
                    attempt + 1,
                    self._MAX_RETRIES,
                    wait_seconds,
                )

                await asyncio.sleep(wait_seconds)

        raise RuntimeError(
            "MediaWiki API retry loop kết thúc bất thường"
        )

    # ================================================================
    # CATEGORY DISCOVERY
    # ================================================================

    async def _list_pages(
        self,
        client: httpx.AsyncClient,
        limit: int,
        category_titles: tuple[str, ...],
        max_depth: int = 4,
    ) -> list[dict[str, Any]]:
        """
        Lấy article namespace 0 bằng BFS qua category tree.

        Category namespace:
            14

        Article namespace:
            0

        Nhiều category seed được xử lý công bằng theo depth.
        """

        if limit <= 0:
            return []

        if max_depth < 0:
            logger.warning(
                "wikivoyage_invalid_category_depth max_depth=%d",
                max_depth,
            )
            return []

        pages: list[dict[str, Any]] = []

        seen_page_ids: set[int] = set()

        seed_categories = tuple(
            dict.fromkeys(category_titles)
        )

        seen_categories = set(seed_categories)

        queue: list[
            tuple[int, int, CategoryCursor]
        ] = []

        sequence = count()

        def enqueue(cursor: CategoryCursor) -> None:
            # Ưu tiên depth thấp trước.
            #
            # sequence đảm bảo ổn định trong cùng depth.
            heappush(
                queue,
                (
                    cursor.depth,
                    next(sequence),
                    cursor,
                ),
            )

        for category_title in seed_categories:
            enqueue(
                CategoryCursor(
                    title=category_title,
                    depth=0,
                )
            )

        while queue and len(pages) < limit:
            _, _, cursor = heappop(queue)

            if cursor.depth > max_depth:
                continue

            logger.info(
                "wikivoyage_category_visit "
                "category=%s depth=%d/%d pages=%d",
                cursor.title,
                cursor.depth,
                max_depth,
                len(pages),
            )

            params: dict[str, Any] = {
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "list": "categorymembers",
                "cmtitle": cursor.title,
                "cmnamespace": "0|14",
                "cmprop": "ids|title|type",
                "cmlimit": "max",
            }

            if cursor.continuation:
                params.update(cursor.continuation)

            try:
                data = await self._get_json(
                    client,
                    params,
                )

                members = (
                    data
                    .get("query", {})
                    .get("categorymembers", [])
                )

                if not isinstance(members, list):
                    raise ValueError(
                        "categorymembers không phải danh sách"
                    )

                child_categories: list[str] = []

                for member in members:
                    namespace = member.get("ns")

                    # ----------------------------------------------
                    # ARTICLE
                    # ----------------------------------------------

                    if namespace == 0:
                        page_id = member.get("pageid")

                        if (
                            isinstance(page_id, int)
                            and page_id not in seen_page_ids
                        ):
                            pages.append(member)

                            seen_page_ids.add(
                                page_id
                            )

                            if len(pages) >= limit:
                                break

                    # ----------------------------------------------
                    # CHILD CATEGORY
                    # ----------------------------------------------

                    elif (
                        namespace == 14
                        and cursor.depth < max_depth
                    ):
                        title = member.get("title")

                        if (
                            isinstance(title, str)
                            and title not in seen_categories
                        ):
                            seen_categories.add(title)

                            child_categories.append(
                                title
                            )

                # ----------------------------------------------
                # PAGINATION CỦA CATEGORY HIỆN TẠI
                # ----------------------------------------------

                continuation = data.get("continue")

                if (
                    len(pages) < limit
                    and isinstance(
                        continuation,
                        dict,
                    )
                ):
                    enqueue(
                        CategoryCursor(
                            title=cursor.title,
                            depth=cursor.depth,
                            continuation=continuation,
                        )
                    )

                # ----------------------------------------------
                # CATEGORY CON
                # ----------------------------------------------

                for title in child_categories:
                    enqueue(
                        CategoryCursor(
                            title=title,
                            depth=cursor.depth + 1,
                        )
                    )

            except (
                httpx.HTTPError,
                RuntimeError,
                ValueError,
            ) as exc:
                logger.warning(
                    "wikivoyage_category_failed "
                    "category=%s depth=%s "
                    "error=%s timestamp=%s",
                    cursor.title,
                    cursor.depth,
                    exc,
                    datetime.now(UTC).isoformat(),
                )

        logger.info(
            "wikivoyage_category_bfs_finished "
            "pages=%d categories=%d queue_remaining=%d max_depth=%d",
            len(pages),
            len(seen_categories),
            len(queue),
            max_depth,
        )

        return pages

    # ================================================================
    # FETCH RAW WIKITEXT
    # ================================================================

    async def _fetch_page_batch_resilient(
        self,
        client: httpx.AsyncClient,
        page_batch: list[dict[str, Any]],
    ) -> list[CrawledRawDocument]:
        """
        Fetch một batch.

        Nếu cả batch lỗi, fallback sang từng page.

        Điều này tránh trường hợp:
            20 pages/batch
            1 request lỗi
            -> mất luôn cả 20 pages.
        """

        page_ids = [
            page["pageid"]
            for page in page_batch
            if isinstance(
                page.get("pageid"),
                int,
            )
        ]

        if not page_ids:
            return []

        try:
            return await self._fetch_pages(
                client,
                page_ids=page_ids,
            )

        except (
            httpx.HTTPError,
            KeyError,
            RuntimeError,
            ValueError,
        ) as exc:
            logger.warning(
                "wikivoyage_fetch_batch_failed "
                "pageids=%s error=%s "
                "fallback=single_page",
                ",".join(
                    str(page_id)
                    for page_id in page_ids
                ),
                exc,
            )

        # ------------------------------------------------------------
        # FALLBACK SINGLE PAGE
        # ------------------------------------------------------------

        documents: list[CrawledRawDocument] = []

        for page_id in page_ids:
            try:
                fetched = await self._fetch_pages(
                    client,
                    page_ids=[page_id],
                )

                documents.extend(fetched)

            except (
                httpx.HTTPError,
                KeyError,
                RuntimeError,
                ValueError,
            ) as exc:
                logger.warning(
                    "wikivoyage_fetch_single_failed "
                    "pageid=%s error=%s "
                    "timestamp=%s",
                    page_id,
                    exc,
                    datetime.now(UTC).isoformat(),
                )

        return documents

    async def _fetch_pages(
        self,
        client: httpx.AsyncClient,
        page_ids: list[int],
    ) -> list[CrawledRawDocument]:
        """
        Lấy revisions của nhiều Wikivoyage page.

        raw_content luôn giữ nguyên Wikitext.
        """

        if not page_ids:
            return []

        params = {
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "prop": "revisions",
            "pageids": "|".join(
                str(page_id)
                for page_id in page_ids
            ),
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
            "redirects": 1,
        }

        data = await self._get_json(
            client,
            params,
        )

        pages = (
            data
            .get("query", {})
            .get("pages", [])
        )

        if not isinstance(pages, list):
            raise ValueError(
                "MediaWiki pages không phải danh sách"
            )

        fetched_at = datetime.now(UTC)

        documents: list[
            CrawledRawDocument
        ] = []

        for page in pages:
            if (
                page.get("missing")
                or page.get("invalid")
            ):
                logger.info(
                    "wikivoyage_missing_page "
                    "pageid=%s",
                    page.get("pageid"),
                )

                continue

            revisions = page.get(
                "revisions",
                [],
            )

            if not revisions:
                logger.info(
                    "wikivoyage_page_without_revision "
                    "pageid=%s title=%s",
                    page.get("pageid"),
                    page.get("title"),
                )

                continue

            revision = revisions[0]

            title = page.get("title")

            main_slot = (
                revision
                .get("slots", {})
                .get("main", {})
            )

            # MediaWiki installations có thể trả:
            #
            #     content
            #
            # hoặc legacy:
            #
            #     *
            #
            # Cả hai đều là raw Wikitext.
            raw_wikitext = main_slot.get(
                "content",
                main_slot.get("*"),
            )

            revision_id = revision.get(
                "revid"
            )

            if not isinstance(title, str):
                logger.warning(
                    "wikivoyage_invalid_title "
                    "pageid=%s",
                    page.get("pageid"),
                )

                continue

            if not isinstance(
                raw_wikitext,
                str,
            ):
                logger.warning(
                    "wikivoyage_invalid_page_payload "
                    "pageid=%s title=%s",
                    page.get("pageid"),
                    title,
                )

                continue

            wiki_title = quote(
                title.replace(" ", "_"),
                safe="",
            )

            documents.append(
                CrawledRawDocument(
                    title=title,
                    source_name=self.config.name,
                    source_url=(
                        f"{self.config.wiki_base_url}"
                        f"/wiki/{wiki_title}"
                    ),
                    license=self.config.license,
                    language=self.config.language,
                    raw_content=raw_wikitext,
                    content_format="wikitext",
                    revision_id=(
                        str(revision_id)
                        if revision_id is not None
                        else None
                    ),
                    fetched_at=fetched_at,
                )
            )

        return documents