import asyncio
import hashlib
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.db.models import (
    Document,
    RawDocument,
)
from app.db.session import (
    AsyncSessionFactory,
    close_db,
    init_db,
)
from pipeline.etl.wikitext_cleaner import (
    clean_wikitext,
)


# ================================================================
# LOGGING
# ================================================================

logging.basicConfig(
    level=logging.WARNING,
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s: "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    __name__
)


# ================================================================
# CONFIG
# ================================================================

READ_BATCH_SIZE = 100


# ================================================================
# HASH
# ================================================================

def calculate_content_hash(
    content: str,
) -> str:
    """
    SHA-256 của plain text sau cleaning.
    """

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


# ================================================================
# PROGRESS
# ================================================================

def print_progress(
    *,
    processed: int,
    total: int,
    inserted: int,
    existing: int,
    errors: int,
) -> None:
    if total > 0:
        percent = (
            processed
            / total
            * 100
        )
    else:
        percent = 100.0

    message = (
        f"\r"
        f"[step-2] "
        f"{processed:>5}/{total:<5} "
        f"({percent:6.2f}%) "
        f"| saved={inserted} "
        f"| existing={existing} "
        f"| errors={errors}"
    )

    print(
        f"{message}\033[K",
        end="",
        flush=True,
    )


# ================================================================
# DATABASE READ
# ================================================================

async def count_raw_documents() -> int:
    async with AsyncSessionFactory() as session:
        statement = select(
            func.count(
                RawDocument.id
            )
        )

        result = await session.execute(
            statement
        )

        return int(
            result.scalar_one()
        )


async def get_raw_batch(
    *,
    offset: int,
    limit: int,
) -> list[RawDocument]:
    """
    Đọc RawDocument theo batch.

    Dataset hiện tại nhỏ nên OFFSET pagination đủ dùng.
    """

    async with AsyncSessionFactory() as session:
        statement = (
            select(RawDocument)
            .order_by(
                RawDocument.fetched_at.asc(),
                RawDocument.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )

        result = await session.execute(
            statement
        )

        return list(
            result.scalars().all()
        )


# ================================================================
# TRANSFORM
# ================================================================

def transform_raw_document(
    raw: RawDocument,
) -> dict[str, Any]:
    """
    RawDocument
        ↓
    Wikitext cleaning
        ↓
    Plain text
        ↓
    SHA-256
        ↓
    Document row

    Không Quality Check.
    Không Entity Extraction.
    """

    content = clean_wikitext(
        raw.raw_content
    )

    content_hash = (
        calculate_content_hash(
            content
        )
    )

    return {
        "raw_document_id": raw.id,

        "title": raw.title,

        "content": content,

        "content_hash": content_hash,

        "source_name": raw.source_name,

        "source_url": raw.source_url,

        "language": raw.language,

        "license": raw.license,

        "revision_id": raw.revision_id,

        "fetched_at": raw.fetched_at,

        "is_active": True,
    }


# ================================================================
# DATABASE INSERT
# ================================================================

async def insert_documents(
    rows: list[
        dict[str, Any]
    ],
) -> int:
    """
    Insert processed documents.

    raw_document_id có UNIQUE constraint.

    Vì vậy chạy script lần 2:
        cùng RawDocument
            ->
        không insert lại.
    """

    if not rows:
        return 0

    async with (
        AsyncSessionFactory.begin()
        as session
    ):
        statement = (
            insert(Document)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=[
                    Document.raw_document_id
                ]
            )
            .returning(
                Document.id
            )
        )

        result = await session.execute(
            statement
        )

        inserted_ids = list(
            result.scalars().all()
        )

        return len(
            inserted_ids
        )


# ================================================================
# PROCESS BATCH
# ================================================================

async def process_batch(
    raw_documents: list[
        RawDocument
    ],
) -> tuple[int, int, int]:
    """
    Return:

        inserted
        existing
        errors
    """

    rows: list[
        dict[str, Any]
    ] = []

    errors = 0

    # Một raw_document_id chỉ xuất hiện một lần trong batch.
    seen_raw_ids: set[str] = set()

    duplicate_in_batch = 0

    for raw in raw_documents:
        raw_id = str(raw.id)

        if raw_id in seen_raw_ids:
            duplicate_in_batch += 1
            continue

        seen_raw_ids.add(
            raw_id
        )

        try:
            row = transform_raw_document(
                raw
            )

            rows.append(
                row
            )

        except Exception as exc:
            errors += 1

            print()

            logger.exception(
                "raw_transform_failed "
                "raw_id=%s "
                "title=%s "
                "error=%s",
                raw.id,
                raw.title,
                exc,
            )

    if not rows:
        return (
            0,
            duplicate_in_batch,
            errors,
        )

    inserted = await insert_documents(
        rows
    )

    # Những row không insert nghĩa là raw_document_id
    # đã tồn tại trong documents.
    existing_in_db = (
        len(rows)
        - inserted
    )

    existing = (
        duplicate_in_batch
        + existing_in_db
    )

    return (
        inserted,
        existing,
        errors,
    )


# ================================================================
# PIPELINE
# ================================================================

async def process_all() -> None:
    """
    STEP 2:

    raw_documents
        ↓
    clean Wikitext
        ↓
    plain text
        ↓
    SHA-256
        ↓
    documents
    """

    total = await count_raw_documents()

    if total == 0:
        print(
            "Không có dữ liệu trong raw_documents."
        )
        return

    print()
    print("=" * 72)
    print("STEP 2 - RAW WIKITEXT -> CLEAN DOCUMENTS")
    print("=" * 72)
    print(f"Raw documents : {total}")
    print(f"Batch size    : {READ_BATCH_SIZE}")
    print("Quality check : disabled")
    print("Entity        : not extracted yet")
    print("=" * 72)
    print()

    processed = 0
    inserted_total = 0
    existing_total = 0
    error_total = 0

    offset = 0

    while offset < total:
        raw_batch = await get_raw_batch(
            offset=offset,
            limit=READ_BATCH_SIZE,
        )

        if not raw_batch:
            break

        (
            inserted,
            existing,
            errors,
        ) = await process_batch(
            raw_batch
        )

        batch_size = len(
            raw_batch
        )

        processed += batch_size
        inserted_total += inserted
        existing_total += existing
        error_total += errors

        offset += batch_size

        print_progress(
            processed=processed,
            total=total,
            inserted=inserted_total,
            existing=existing_total,
            errors=error_total,
        )

    print_progress(
        processed=processed,
        total=total,
        inserted=inserted_total,
        existing=existing_total,
        errors=error_total,
    )

    print()
    print()

    print("=" * 72)
    print("STEP 2 COMPLETED")
    print("=" * 72)
    print(f"Processed : {processed}")
    print(f"Saved     : {inserted_total}")
    print(f"Existing  : {existing_total}")
    print(f"Errors    : {error_total}")
    print("=" * 72)


# ================================================================
# ENTRY POINT
# ================================================================

async def main() -> None:
    await init_db()

    try:
        await process_all()

    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(
        main()
    )