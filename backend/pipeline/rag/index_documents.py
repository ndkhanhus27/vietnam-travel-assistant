from __future__ import annotations

import argparse
import asyncio
import uuid

from qdrant_client.models import PointStruct
from sqlalchemy import select

from app.core.config import settings
from app.db.models import Document
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
    }


# ================================================================
# INDEX DOCUMENT
# ================================================================

def index_document(
    *,
    document: Document,
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

    if failed:
        raise RuntimeError(
            f"RAG index incomplete: {failed} document(s) failed."
        )


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
