from __future__ import annotations

import argparse
import asyncio
import uuid
from collections import defaultdict

from qdrant_client.models import PointStruct
from sqlalchemy import select

from app.core.config import settings
from app.db.models import Document, EntityCandidate
from app.db.session import AsyncSessionFactory, close_db
from pipeline.rag.bge_tokenizer import BgeM3Tokenizer
from pipeline.rag.chunker import TextChunk, chunk_document
from pipeline.rag.embedder import BgeM3Embedder
from pipeline.rag.qdrant_store import TravelQdrantStore


# ================================================================
# LOAD DATA
# ================================================================

async def load_documents(
    limit: int | None = None,
) -> list[Document]:
    async with AsyncSessionFactory() as session:
        statement = (
            select(Document)
            .where(Document.is_active.is_(True))
            .order_by(Document.title.asc())
        )

        if limit is not None and limit > 0:
            statement = statement.limit(limit)

        result = await session.execute(statement)

        return list(result.scalars().all())


async def load_candidates(
    document_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[EntityCandidate]]:
    if not document_ids:
        return {}

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(
                EntityCandidate
            )
            .where(EntityCandidate.document_id.in_(document_ids))
            .order_by(EntityCandidate.confidence.desc())
        )

        candidates = list(result.scalars().all())

    grouped: dict[uuid.UUID, list[EntityCandidate]] = defaultdict(list)

    for candidate in candidates:
        grouped[candidate.document_id].append(candidate)

    return dict(grouped)


# ================================================================
# ENTITY METADATA
# ================================================================

def build_entity_metadata(
    candidates: list[EntityCandidate],
) -> tuple[
    list[str],
    list[str],
    list[str],
]:
    entity_names: list[str] = []
    entity_types: list[str] = []
    primary_entities: list[str] = []

    seen_names: set[str] = set()
    seen_types: set[str] = set()
    seen_primary: set[str] = set()

    for candidate in candidates:
        name = candidate.name.strip() if candidate.name else ""

        if name and name.casefold() not in seen_names:
            entity_names.append(name)
            seen_names.add(name.casefold())

        entity_type = (
            candidate.entity_type.strip() if candidate.entity_type else ""
        )

        if entity_type and entity_type not in seen_types:
            entity_types.append(entity_type)
            seen_types.add(entity_type)

        if (
            candidate.role == "primary"
            and name
            and name.casefold() not in seen_primary
        ):
            primary_entities.append(name)
            seen_primary.add(name.casefold())

    return (
        entity_names,
        entity_types,
        primary_entities,
    )


# ================================================================
# POINT ID
# ================================================================

def make_chunk_id(
    *,
    document_id: uuid.UUID,
    content_hash: str,
    chunk_index: int,
) -> str:
    """
    Deterministic UUID.

    Nếu document/chunk không đổi:
        point ID không đổi.

    Nếu document content_hash đổi:
        point IDs đổi.
    """

    value = f"{document_id}:{content_hash}:{chunk_index}"

    return str(uuid.uuid5(uuid.NAMESPACE_URL, value))


# ================================================================
# PAYLOAD
# ================================================================

def build_payload(
    *,
    document: Document,
    chunk: TextChunk,
    entities: list[str],
    entity_types: list[str],
    primary_entities: list[str],
) -> dict:
    return {
        "document_id": str(document.id),
        "chunk_index": chunk.chunk_index,
        "title": document.title,
        "content": chunk.content,
        "token_count": chunk.token_count,
        "content_hash": document.content_hash,
        "source_name": document.source_name,
        "source_url": document.source_url,
        "language": document.language,
        "license": document.license,
        "revision_id": document.revision_id,
        "fetched_at": (
            document.fetched_at.isoformat() if document.fetched_at else None
        ),
        "entities": entities,
        "entity_types": entity_types,
        "primary_entities": primary_entities,
    }


# ================================================================
# INDEX DOCUMENT
# ================================================================

def index_document(
    *,
    document: Document,
    candidates: list[EntityCandidate],
    tokenizer: BgeM3Tokenizer,
    embedder: BgeM3Embedder,
    store: TravelQdrantStore,
) -> int:
    chunks = chunk_document(
        content=document.content,
        tokenizer=tokenizer,
        chunk_size=settings.rag_chunk_size,
        overlap=settings.rag_chunk_overlap,
    )

    if not chunks:
        return 0

    (
        entity_names,
        entity_types,
        primary_entities,
    ) = build_entity_metadata(candidates)

    texts = [chunk.content for chunk in chunks]

    vectors = embedder.encode(
        texts,
        batch_size=settings.rag_embedding_batch_size,
    )

    if len(vectors) != len(chunks):
        raise RuntimeError(
            "Số embeddings không khớp "
            "số chunks."
        )

    points: list[PointStruct] = []

    for chunk, vector in zip(
        chunks,
        vectors,
    ):
        chunk_id = make_chunk_id(
            document_id=document.id,
            content_hash=document.content_hash,
            chunk_index=chunk.chunk_index,
        )

        payload = build_payload(
            document=document,
            chunk=chunk,
            entities=entity_names,
            entity_types=entity_types,
            primary_entities=primary_entities,
        )

        points.append(
            PointStruct(
                id=chunk_id,
                vector=vector.astype(float).tolist(),
                payload=payload,
            )
        )

    store.upsert(points)

    return len(points)


# ================================================================
# RUN
# ================================================================

async def run(
    *,
    recreate: bool,
    limit: int | None,
) -> None:
    print()
    print("=" * 78)
    print("STEP 5 - BUILD REAL RAG INDEX")
    print("=" * 78)

    documents = await load_documents(limit=limit)

    print(f"Documents : {len(documents)}")

    if not documents:
        print("Không có document để index.")
        return

    candidates_map = await load_candidates([document.id for document in documents])

    total_candidates = sum(len(value) for value in candidates_map.values())

    print(f"Entities  : {total_candidates}")
    print(f"Model     : {settings.rag_embedding_model}")
    print(f"Chunk     : {settings.rag_chunk_size}/{settings.rag_chunk_overlap}")
    print(f"Qdrant    : {settings.qdrant_url}")
    print(f"Collection: {settings.qdrant_collection}")

    print("=" * 78)
    print()

    # ------------------------------------------------------------
    # Init components
    # ------------------------------------------------------------

    tokenizer = BgeM3Tokenizer()
    embedder = BgeM3Embedder()
    store = TravelQdrantStore()

    if recreate:
        store.recreate_collection()
    else:
        store.ensure_collection()

    # ------------------------------------------------------------
    # Index
    # ------------------------------------------------------------

    indexed_documents = 0
    indexed_chunks = 0
    failed = 0

    total = len(documents)

    for index, document in enumerate(
        documents,
        start=1,
    ):
        try:
            chunk_count = index_document(
                document=document,
                candidates=candidates_map.get(document.id, []),
                tokenizer=tokenizer,
                embedder=embedder,
                store=store,
            )

            indexed_documents += 1
            indexed_chunks += chunk_count

            print(
                f"[{index:>4}/{total}] "
                f"{document.title[:40]:<40} "
                f"| chunks={chunk_count}"
            )

        except Exception as exc:
            failed += 1

            print(
                f"[{index:>4}/{total}] "
                f"FAILED "
                f"{document.title}: "
                f"{exc}"
            )

    print()
    print("=" * 78)
    print("RAG INDEX COMPLETED")
    print("=" * 78)

    print(f"Documents indexed : {indexed_documents}")
    print(f"Chunks indexed    : {indexed_chunks}")
    print(f"Failed            : {failed}")
    print(f"Qdrant count      : {store.count()}")

    print("=" * 78)


# ================================================================
# CLI
# ================================================================

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Xóa travel_chunks cũ và rebuild từ đầu.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Giới hạn số documents. 0 = toàn bộ.",
    )

    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    limit = args.limit if args.limit > 0 else None

    try:
        await run(
            recreate=args.recreate,
            limit=limit,
        )
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
