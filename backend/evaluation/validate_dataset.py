from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


VALID_INTENTS = {
    "GENERAL",
    "FACTUAL_TRAVEL",
    "RECOMMENDATION",
    "COMPARISON",
    "ITINERARY",
    "WEATHER",
    "ROUTING",
    "CURRENT_INFO",
    "BUDGET",
    "OUT_OF_SCOPE",
}

VALID_TOOLS = {
    "search_travel_knowledge",
    "web_search",
    "weather",
    "map_location",
    "routing",
    "budget_calculator",
    "distance_matrix",
}

VALID_RETRIEVAL_MODES = {
    "DIRECT",
    "RAG_FIRST",
    "WEB_FIRST",
    "TOOL_ONLY",
    "MIXED",
}

VALID_REVIEW_STATUSES = {
    "pending",
    "approved",
    "rejected",
}

REQUIRED_FIELDS = {
    "id",
    "query",
    "expected_intent",
    "expected_tools",
    "expected_retrieval_mode",
    "entities",
    "requires_citations",
    "category",
    "relevant_chunk_ids",
    "notes",
    "review_status",
}


def parse_args() -> argparse.Namespace:
    default_dataset = Path(__file__).with_name("dataset.jsonl")
    parser = argparse.ArgumentParser(
        description="Validate the travel-agent evaluation dataset.",
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        default=default_dataset,
    )
    parser.add_argument(
        "--qdrant-url",
        default="http://localhost:6333",
    )
    parser.add_argument(
        "--collection",
        default="travel_chunks",
    )
    parser.add_argument(
        "--skip-chunk-check",
        action="store_true",
        help="Skip Qdrant lookup when validating offline.",
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"Cannot read {path}: {exc}"]

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            errors.append(f"line {line_number}: blank lines are not allowed")
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(value, dict):
            errors.append(f"line {line_number}: expected a JSON object")
            continue
        value["__line__"] = line_number
        records.append(value)
    return records, errors


def is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item.strip())
        for item in value
    )


def validate_records(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_ids: dict[str, int] = {}
    seen_queries: dict[str, int] = {}

    for record in records:
        line_number = int(record["__line__"])
        fields = set(record) - {"__line__"}
        missing = REQUIRED_FIELDS - fields
        if missing:
            errors.append(
                f"line {line_number}: missing fields {sorted(missing)}"
            )

        case_id = record.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            errors.append(f"line {line_number}: id must be a non-empty string")
        elif case_id in seen_ids:
            errors.append(
                f"line {line_number}: duplicate id {case_id!r} "
                f"(first seen on line {seen_ids[case_id]})"
            )
        else:
            seen_ids[case_id] = line_number

        query = record.get("query")
        if not isinstance(query, str) or not query.strip():
            errors.append(
                f"line {line_number}: query must be a non-empty string"
            )
        else:
            normalized_query = " ".join(query.casefold().split())
            if normalized_query in seen_queries:
                errors.append(
                    f"line {line_number}: duplicate query "
                    f"(first seen on line {seen_queries[normalized_query]})"
                )
            else:
                seen_queries[normalized_query] = line_number

        intent = record.get("expected_intent")
        if intent not in VALID_INTENTS:
            errors.append(
                f"line {line_number}: invalid expected_intent {intent!r}"
            )

        tools = record.get("expected_tools")
        if not is_string_list(tools) and tools != []:
            errors.append(
                f"line {line_number}: expected_tools must be a string list"
            )
        elif isinstance(tools, list):
            invalid_tools = set(tools) - VALID_TOOLS
            if invalid_tools:
                errors.append(
                    f"line {line_number}: invalid tools "
                    f"{sorted(invalid_tools)}"
                )
            if len(tools) != len(set(tools)):
                errors.append(
                    f"line {line_number}: expected_tools contains duplicates"
                )

        mode = record.get("expected_retrieval_mode")
        if mode not in VALID_RETRIEVAL_MODES:
            errors.append(
                f"line {line_number}: invalid retrieval mode {mode!r}"
            )

        if not is_string_list(record.get("entities")) and record.get(
            "entities"
        ) != []:
            errors.append(
                f"line {line_number}: entities must be a string list"
            )

        if not isinstance(record.get("requires_citations"), bool):
            errors.append(
                f"line {line_number}: requires_citations must be boolean"
            )

        category = record.get("category")
        if not isinstance(category, str) or not category.strip():
            errors.append(
                f"line {line_number}: category must be a non-empty string"
            )

        chunk_ids = record.get("relevant_chunk_ids")
        if not is_string_list(chunk_ids) and chunk_ids != []:
            errors.append(
                f"line {line_number}: relevant_chunk_ids must be a string list"
            )
        elif isinstance(chunk_ids, list) and len(chunk_ids) != len(
            set(chunk_ids)
        ):
            errors.append(
                f"line {line_number}: relevant_chunk_ids contains duplicates"
            )

        if record.get("review_status") not in VALID_REVIEW_STATUSES:
            errors.append(
                f"line {line_number}: invalid review_status "
                f"{record.get('review_status')!r}"
            )

        notes = record.get("notes")
        if notes is not None and not isinstance(notes, str):
            errors.append(
                f"line {line_number}: notes must be a string or null"
            )

    return errors


def fetch_qdrant_ids(qdrant_url: str, collection: str) -> set[str]:
    endpoint = (
        f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll"
    )
    result: set[str] = set()
    offset: object | None = None

    while True:
        payload: dict[str, object] = {
            "limit": 256,
            "with_payload": False,
            "with_vector": False,
        }
        if offset is not None:
            payload["offset"] = offset
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.load(response)
        page = body.get("result", {})
        points = page.get("points", [])
        result.update(str(point["id"]) for point in points)
        offset = page.get("next_page_offset")
        if offset is None:
            return result


def validate_chunk_ids(
    records: list[dict[str, Any]],
    existing_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    for record in records:
        line_number = record["__line__"]
        chunk_ids = record.get("relevant_chunk_ids", [])
        if not isinstance(chunk_ids, list):
            continue
        for chunk_id in chunk_ids:
            if not isinstance(chunk_id, str):
                continue
            if chunk_id not in existing_ids:
                errors.append(
                    f"line {line_number}: chunk ID does not exist: {chunk_id}"
                )
    return errors


def print_summary(
    records: list[dict[str, Any]],
    *,
    chunk_check_skipped: bool,
) -> None:
    category_counts = Counter(
        record.get("category", "<missing>") for record in records
    )
    intent_counts = Counter(
        record.get("expected_intent", "<missing>") for record in records
    )
    referenced_ids: set[str] = set()
    for record in records:
        chunk_ids = record.get("relevant_chunk_ids", [])
        if isinstance(chunk_ids, list):
            referenced_ids.update(
                chunk_id
                for chunk_id in chunk_ids
                if isinstance(chunk_id, str)
            )

    print(f"Cases: {len(records)}")
    print("Category counts:")
    for category, count in sorted(category_counts.items()):
        print(f"  {category}: {count}")
    print("Intent counts:")
    for intent, count in sorted(intent_counts.items()):
        print(f"  {intent}: {count}")
    print(f"Distinct referenced chunks: {len(referenced_ids)}")
    print(
        "Chunk existence check: "
        + ("SKIPPED" if chunk_check_skipped else "PASSED")
    )


def main() -> int:
    args = parse_args()
    records, errors = read_jsonl(args.dataset)
    errors.extend(validate_records(records))

    if not args.skip_chunk_check:
        try:
            existing_ids = fetch_qdrant_ids(
                args.qdrant_url,
                args.collection,
            )
        except (OSError, ValueError, urllib.error.URLError) as exc:
            errors.append(f"Qdrant chunk validation failed: {exc}")
        else:
            errors.extend(validate_chunk_ids(records, existing_ids))

    print_summary(
        records,
        chunk_check_skipped=args.skip_chunk_check,
    )
    if errors:
        print("\nValidation errors:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("\nDATASET VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
