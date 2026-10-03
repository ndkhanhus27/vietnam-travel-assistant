from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.db.models import Document, EntityCandidate
from app.db.session import AsyncSessionFactory, close_db


FORMAT_VERSION = 1


def _datetime(value: datetime) -> str:
    return value.isoformat()


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 string")
    return datetime.fromisoformat(value)


def _parse_uuid(value: Any, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def validate_bundle(bundle: Any) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise ValueError("Corpus bundle must be a JSON object")
    if bundle.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported corpus bundle format_version")

    documents = bundle.get("documents")
    candidates = bundle.get("entity_candidates")
    if not isinstance(documents, list) or not isinstance(candidates, list):
        raise ValueError("Corpus bundle must contain both row lists")

    document_ids = {
        _parse_uuid(row.get("id"), "documents.id")
        for row in documents
        if isinstance(row, dict)
    }
    if len(document_ids) != len(documents):
        raise ValueError("Document rows contain invalid or duplicate IDs")

    candidate_ids: set[uuid.UUID] = set()
    for row in candidates:
        if not isinstance(row, dict):
            raise ValueError("Entity candidate rows must be JSON objects")
        candidate_id = _parse_uuid(row.get("id"), "entity_candidates.id")
        if candidate_id in candidate_ids:
            raise ValueError("Entity candidate rows contain duplicate IDs")
        candidate_ids.add(candidate_id)
        document_id = _parse_uuid(
            row.get("document_id"),
            "entity_candidates.document_id",
        )
        if document_id not in document_ids:
            raise ValueError("Entity candidate references a missing document")

    return bundle


def _open_text(path: Path, mode: str, *, compressed: bool | None = None):
    if compressed is None:
        compressed = path.suffix == ".gz"
    if compressed:
        return gzip.open(path, mode, encoding="utf-8")
    return path.open(mode, encoding="utf-8")


async def export_corpus(path: Path) -> tuple[int, int]:
    async with AsyncSessionFactory() as session:
        documents = list(
            (
                await session.execute(select(Document).order_by(Document.id))
            ).scalars()
        )
        candidates = list(
            (
                await session.execute(
                    select(EntityCandidate).order_by(EntityCandidate.id)
                )
            ).scalars()
        )

    bundle = {
        "format_version": FORMAT_VERSION,
        "documents": [
            {
                "id": str(row.id),
                "title": row.title,
                "content": row.content,
                "content_hash": row.content_hash,
                "source_name": row.source_name,
                "source_url": row.source_url,
                "language": row.language,
                "license": row.license,
                "revision_id": row.revision_id,
                "fetched_at": _datetime(row.fetched_at),
                "is_active": row.is_active,
                "created_at": _datetime(row.created_at),
            }
            for row in documents
        ],
        "entity_candidates": [
            {
                "id": str(row.id),
                "document_id": str(row.document_id),
                "name": row.name,
                "normalized_name": row.normalized_name,
                "entity_type": row.entity_type,
                "role": row.role,
                "mention_text": row.mention_text,
                "confidence": row.confidence,
                "created_at": _datetime(row.created_at),
            }
            for row in candidates
        ],
    }
    validate_bundle(bundle)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with _open_text(
        temporary,
        "wt",
        compressed=path.suffix == ".gz",
    ) as stream:
        json.dump(bundle, stream, ensure_ascii=False, separators=(",", ":"))
    temporary.replace(path)
    return len(documents), len(candidates)


def _document_rows(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "id": _parse_uuid(row["id"], "documents.id"),
            "fetched_at": _parse_datetime(
                row["fetched_at"], "documents.fetched_at"
            ),
            "created_at": _parse_datetime(
                row["created_at"], "documents.created_at"
            ),
        }
        for row in bundle["documents"]
    ]


def _candidate_rows(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "id": _parse_uuid(row["id"], "entity_candidates.id"),
            "document_id": _parse_uuid(
                row["document_id"], "entity_candidates.document_id"
            ),
            "created_at": _parse_datetime(
                row["created_at"], "entity_candidates.created_at"
            ),
        }
        for row in bundle["entity_candidates"]
    ]


async def import_corpus(path: Path) -> tuple[int, int]:
    with _open_text(path, "rt") as stream:
        bundle = validate_bundle(json.load(stream))

    document_rows = _document_rows(bundle)
    candidate_rows = _candidate_rows(bundle)

    async with AsyncSessionFactory.begin() as session:
        if document_rows:
            statement = insert(Document).values(document_rows)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Document.id],
                    set_={
                        column.name: getattr(statement.excluded, column.name)
                        for column in Document.__table__.columns
                        if column.name != "id"
                    },
                )
            )
        if candidate_rows:
            statement = insert(EntityCandidate).values(candidate_rows)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[EntityCandidate.id],
                    set_={
                        column.name: getattr(statement.excluded, column.name)
                        for column in EntityCandidate.__table__.columns
                        if column.name != "id"
                    },
                )
            )

    async with AsyncSessionFactory() as session:
        document_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(Document)
                )
            ).scalar_one()
        )
        candidate_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(EntityCandidate)
                )
            ).scalar_one()
        )
    return document_count, candidate_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transfer only the durable travel corpus tables."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--output", type=Path, required=True)

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--input", type=Path, required=True)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    try:
        if args.command == "export":
            documents, candidates = await export_corpus(args.output)
            print(f"Documents exported       : {documents}")
            print(f"Entity candidates exported: {candidates}")
            return

        documents, candidates = await import_corpus(args.input)
        print(f"Documents in database       : {documents}")
        print(f"Entity candidates in database: {candidates}")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
