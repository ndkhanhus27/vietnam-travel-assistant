"""Copy a Qdrant collection without corpus entities; preserve IDs and vectors."""
from __future__ import annotations

import argparse
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from app.core.config import settings


ENTITY_FIELDS = frozenset({"entities", "entity_types", "primary_entities"})


def clean_payload(payload: dict | None) -> dict:
    return {key: value for key, value in (payload or {}).items() if key not in ENTITY_FIELDS}


def copy_index(client: QdrantClient, source: str, target: str) -> int:
    if source == target:
        raise ValueError("Source and target must differ")
    if client.collection_exists(target):
        raise ValueError("Target already exists; use a new collection name")
    info = client.get_collection(source)
    expected = client.count(source, exact=True).count
    if not expected:
        raise ValueError("Source collection is empty")
    if info.config.params.sparse_vectors:
        raise ValueError("This copier supports the current dense-only collection")
    client.create_collection(target, vectors_config=info.config.params.vectors)
    offset = None
    copied = 0
    while True:
        records, offset = client.scroll(
            source, offset=offset, limit=128, with_payload=True, with_vectors=True,
        )
        points = [PointStruct(id=row.id, vector=row.vector, payload=clean_payload(row.payload)) for row in records]
        if points:
            client.upsert(target, points=points, wait=True)
        copied += len(points)
        if offset is None:
            break
    actual = client.count(target, exact=True).count
    if copied != expected or actual != expected or client.count(source, exact=True).count != expected:
        raise RuntimeError("Count mismatch; do not activate the target collection")
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=settings.qdrant_collection)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    client = QdrantClient(url=settings.qdrant_url, timeout=60)
    try:
        count = copy_index(client, args.source, args.target)
        print(f"Copied {count} points to {args.target}; source unchanged. Restart backend after switching QDRANT_COLLECTION.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
