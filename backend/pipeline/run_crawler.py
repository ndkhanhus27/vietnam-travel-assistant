import asyncio
import logging

from app.db.models import RawDocument
from app.db.session import AsyncSessionFactory, close_db, init_db
from pipeline.crawlers.base_crawler import APPROVED_SOURCES
from pipeline.crawlers.wikivoyage_crawler import WikivoyageCrawler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def save_all(
    crawler: WikivoyageCrawler,
    limit: int = 1_000,
    batch_size: int = 50,
) -> int:
    """
    Crawl Wikivoyage rồi lưu dần xuống PostgreSQL theo batch.

    Mỗi batch:
        add_all()
            ↓
        flush()
            ↓
        commit()

    Ví dụ:
        50 records  -> commit
        50 records  -> commit
        50 records  -> commit
        ...
    """

    logger.info(
        "Bắt đầu crawl source=%s limit=%d",
        crawler.config.name,
        limit,
    )

    documents = await crawler.crawl(limit=limit)

    if not documents:
        logger.warning(
            "crawl_completed source=%s saved=0",
            crawler.config.name,
        )
        return 0

    total = len(documents)
    saved_total = 0

    logger.info(
        "Crawl xong %d documents. "
        "Bắt đầu lưu theo batch_size=%d...",
        total,
        batch_size,
    )

    for start in range(0, total, batch_size):
        batch = documents[start : start + batch_size]

        # Mỗi batch là một transaction riêng.
        async with AsyncSessionFactory() as session:
            try:
                rows = [
                    RawDocument(
                        source_name=raw.source_name,
                        source_url=raw.source_url,
                        license=raw.license,
                        language=raw.language,
                        title=raw.title,
                        raw_content=raw.raw_content,
                        content_format=raw.content_format,
                        revision_id=raw.revision_id,
                        fetched_at=raw.fetched_at,
                    )
                    for raw in batch
                ]

                session.add_all(rows)

                # Gửi INSERT xuống PostgreSQL.
                await session.flush()

                # Commit batch này ngay lập tức.
                await session.commit()

            except Exception:
                await session.rollback()

                logger.exception(
                    "save_batch_failed "
                    "source=%s start=%d batch_size=%d",
                    crawler.config.name,
                    start,
                    len(batch),
                )

                raise

        saved_total += len(batch)

        percent = (
            saved_total / total * 100
            if total
            else 100
        )

        print(
            f"\rĐang lưu: {percent:6.2f}% "
            f"[{saved_total}/{total}]",
            end="",
            flush=True,
        )

        logger.info(
            "batch_saved "
            "source=%s batch=%d saved=%d/%d",
            crawler.config.name,
            start // batch_size + 1,
            saved_total,
            total,
        )

    print()

    logger.info(
        "crawl_completed "
        "source=%s crawled=%d saved=%d",
        crawler.config.name,
        total,
        saved_total,
    )

    return saved_total


async def main() -> None:
    await init_db()

    try:
        crawler = WikivoyageCrawler(
            APPROVED_SOURCES["wikivoyage_vi"]
        )

        await save_all(
            crawler,
            limit=1000,
            batch_size=50,
        )

    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())