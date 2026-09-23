import asyncio
import logging
from datetime import (
    UTC,
    datetime,
)

from sqlalchemy import (
    delete,
    select,
)

from app.core.config import (
    settings,
)

from app.db.models import (
    Document,
    EntityCandidate,
    EntityExtractionRun,
)

from app.db.session import (
    AsyncSessionFactory,
    close_db,
    init_db,
)

from pipeline.entity.ai_extractor import (
    AIEntityExtractor,
)

from pipeline.entity.normalizer import (
    normalize_entity_name,
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
# PROGRESS
# ================================================================

def print_progress(
    *,
    processed: int,
    total: int,
    completed: int,
    failed: int,
    candidates: int,
    title: str,
) -> None:
    if total:
        percent = (
            processed
            / total
            * 100
        )
    else:
        percent = 100.0

    short_title = (
        title[:35]
        if title
        else ""
    )

    message = (
        f"\r"
        f"[entity-ai] "
        f"{processed:>4}/{total:<4} "
        f"({percent:6.2f}%) "
        f"| ok={completed} "
        f"| failed={failed} "
        f"| candidates={candidates}"
    )

    if short_title:
        message += (
            f" | {short_title}"
        )

    print(
        f"{message}\033[K",
        end="",
        flush=True,
    )


# ================================================================
# GET PENDING DOCUMENTS
# ================================================================

async def get_pending_documents(
) -> list[Document]:
    version = (
        settings
        .entity_extractor_version
    )

    async with (
        AsyncSessionFactory()
        as session
    ):
        completed_exists = (
            select(
                EntityExtractionRun.id
            )
            .where(
                EntityExtractionRun
                .document_id
                == Document.id,

                EntityExtractionRun
                .extractor_version
                == version,

                EntityExtractionRun
                .status
                == "completed",
            )
            .exists()
        )

        statement = (
            select(Document)
            .where(
                Document
                .is_active
                .is_(True),

                ~completed_exists,
            )
            .order_by(
                Document
                .created_at
                .asc(),

                Document.id.asc(),
            )
        )

        result = (
            await session.execute(
                statement
            )
        )

        return list(
            result
            .scalars()
            .all()
        )


# ================================================================
# START RUN
# ================================================================

async def start_extraction_run(
    document: Document,
) -> EntityExtractionRun:
    version = (
        settings
        .entity_extractor_version
    )

    async with (
        AsyncSessionFactory.begin()
        as session
    ):
        result = (
            await session.execute(
                select(
                    EntityExtractionRun
                )
                .where(
                    EntityExtractionRun
                    .document_id
                    == document.id,

                    EntityExtractionRun
                    .extractor_version
                    == version,
                )
            )
        )

        run = (
            result
            .scalar_one_or_none()
        )

        now = datetime.now(UTC)

        if run is None:
            run = (
                EntityExtractionRun(
                    document_id=(
                        document.id
                    ),
                    extractor_version=(
                        version
                    ),
                    model_name=(
                        settings
                        .gemini_model
                    ),
                    status="running",
                    candidate_count=0,
                    error_message=None,
                    started_at=now,
                    completed_at=None,
                )
            )

            session.add(
                run
            )

            await session.flush()

        else:
            run.model_name = (
                settings.gemini_model
            )

            run.status = (
                "running"
            )

            run.candidate_count = 0

            run.error_message = None

            run.started_at = now

            run.completed_at = None

            # Retry:
            # xóa candidate của run cũ.
            await session.execute(
                delete(
                    EntityCandidate
                )
                .where(
                    EntityCandidate
                    .extraction_run_id
                    == run.id
                )
            )

        return run


# ================================================================
# SAVE
# ================================================================

async def save_candidates(
    *,
    document: Document,
    run: EntityExtractionRun,
    candidates,
) -> int:
    async with (
        AsyncSessionFactory.begin()
        as session
    ):
        # Defensive cleanup.
        await session.execute(
            delete(
                EntityCandidate
            )
            .where(
                EntityCandidate
                .extraction_run_id
                == run.id
            )
        )

        rows: list[
            EntityCandidate
        ] = []

        seen: set[
            tuple[str, str]
        ] = set()

        for candidate in candidates:
            normalized_name = (
                normalize_entity_name(
                    candidate.name
                )
            )

            if not normalized_name:
                continue

            key = (
                normalized_name,
                candidate.entity_type,
            )

            if key in seen:
                continue

            seen.add(key)

            rows.append(
                EntityCandidate(
                    extraction_run_id=(
                        run.id
                    ),
                    document_id=(
                        document.id
                    ),
                    name=(
                        candidate
                        .name
                        .strip()
                    ),
                    normalized_name=(
                        normalized_name
                    ),
                    entity_type=(
                        candidate
                        .entity_type
                    ),
                    role=(
                        candidate.role
                    ),
                    mention_text=(
                        candidate
                        .mention_text
                        .strip()
                        or None
                    ),
                    confidence=(
                        candidate
                        .confidence
                    ),
                    resolution_status=(
                        "pending"
                    ),
                    resolved_entity_id=None,
                )
            )

        session.add_all(
            rows
        )

        run_db = await session.get(
            EntityExtractionRun,
            run.id,
        )

        if run_db is None:
            raise RuntimeError(
                "EntityExtractionRun "
                f"không tồn tại: {run.id}"
            )

        run_db.status = (
            "completed"
        )

        run_db.candidate_count = (
            len(rows)
        )

        run_db.error_message = None

        run_db.completed_at = (
            datetime.now(UTC)
        )

        return len(rows)


# ================================================================
# FAIL
# ================================================================

async def mark_run_failed(
    *,
    run_id,
    error: Exception,
) -> None:
    async with (
        AsyncSessionFactory.begin()
        as session
    ):
        run = await session.get(
            EntityExtractionRun,
            run_id,
        )

        if run is None:
            return

        run.status = "failed"

        run.error_message = (
            str(error)[:5000]
        )

        run.completed_at = (
            datetime.now(UTC)
        )


# ================================================================
# PIPELINE
# ================================================================

async def process_all() -> None:
    documents = (
        await get_pending_documents()
    )

    total = len(
        documents
    )

    if total == 0:
        print()
        print(
            "Không có document "
            "nào cần entity extraction."
        )
        return

    print()
    print("=" * 72)
    print(
        "STEP 3B - "
        "AI ENTITY CANDIDATE EXTRACTION"
    )
    print("=" * 72)

    print(
        f"Documents : {total}"
    )

    print(
        f"Model     : "
        f"{settings.gemini_model}"
    )

    print(
        f"Version   : "
        f"{settings.entity_extractor_version}"
    )

    print(
        "Wikidata  : not resolved yet"
    )

    print("=" * 72)
    print()

    extractor = (
        AIEntityExtractor()
    )

    processed = 0
    completed = 0
    failed = 0
    candidate_total = 0

    for document in documents:
        run = (
            await start_extraction_run(
                document
            )
        )

        try:
            candidates = (
                await extractor.extract(
                    title=document.title,
                    content=document.content,
                )
            )

            saved = (
                await save_candidates(
                    document=document,
                    run=run,
                    candidates=candidates,
                )
            )

            completed += 1

            candidate_total += (
                saved
            )

        except Exception as exc:
            failed += 1

            await mark_run_failed(
                run_id=run.id,
                error=exc,
            )

            print()

            logger.exception(
                "entity_extraction_failed "
                "document_id=%s "
                "title=%s "
                "error=%s",
                document.id,
                document.title,
                exc,
            )

        processed += 1

        print_progress(
            processed=processed,
            total=total,
            completed=completed,
            failed=failed,
            candidates=(
                candidate_total
            ),
            title=document.title,
        )

    print()
    print()

    print("=" * 72)
    print("STEP 3B COMPLETED")
    print("=" * 72)

    print(
        f"Processed  : "
        f"{processed}"
    )

    print(
        f"Completed  : "
        f"{completed}"
    )

    print(
        f"Failed     : "
        f"{failed}"
    )

    print(
        f"Candidates : "
        f"{candidate_total}"
    )

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