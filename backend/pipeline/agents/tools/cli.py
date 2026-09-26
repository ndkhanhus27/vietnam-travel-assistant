from __future__ import annotations

import argparse

from .knowledge import TravelKnowledgeTool


def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Travel Knowledge Tool Test"
        )
    )

    parser.add_argument(
        "query",
        nargs="+",
    )

    parser.add_argument(
        "--entities",
        nargs="*",
        default=[],
    )

    parser.add_argument(
        "--require-all",
        action="store_true",
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    query = " ".join(
        args.query
    ).strip()

    tool = (
        TravelKnowledgeTool()
    )

    result = tool.search(
        task_id="manual_test",

        query=query,

        entities=(
            args.entities
        ),

        require_all_entities=(
            args.require_all
        ),
    )

    print()

    print("=" * 90)
    print(
        "STEP 3B - ADAPTIVE TRAVEL KNOWLEDGE TOOL"
    )
    print("=" * 90)

    print(
        f"Query             : "
        f"{query}"
    )

    print(
        f"Status            : "
        f"{result.status.value}"
    )

    print(
        f"Source count      : "
        f"{result.source_count}"
    )

    print(
        f"Error             : "
        f"{result.error}"
    )

    # ========================================================
    # COVERAGE
    # ========================================================

    print()

    if result.coverage:

        print(
            f"Required entities : "
            f"{result.coverage.required_entities}"
        )

        print(
            f"Covered entities  : "
            f"{result.coverage.covered_entities}"
        )

        print(
            f"Missing entities  : "
            f"{result.coverage.missing_entities}"
        )

        print(
            f"Coverage enough   : "
            f"{result.coverage.sufficient}"
        )

    # ========================================================
    # DIAGNOSTICS
    # ========================================================

    rag_covered_entities = result.data.get(
        "rag_covered_entities",
        [],
    )
    rag_missing_entities = result.data.get(
        "rag_missing_entities",
        [],
    )
    web_covered_entities = result.data.get(
        "web_covered_entities",
        [],
    )
    web_fallback_used = result.data.get(
        "web_fallback_used",
        False,
    )
    fallback_required = result.data.get(
        "fallback_required",
        False,
    )

    print()

    print(
        f"RAG covered       : "
        f"{rag_covered_entities}"
    )

    print(
        f"RAG missing       : "
        f"{rag_missing_entities}"
    )

    print(
        f"Web covered       : "
        f"{web_covered_entities}"
    )

    print(
        f"Web fallback used : "
        f"{web_fallback_used}"
    )

    print(
        f"Fallback required : "
        f"{fallback_required}"
    )

    # ========================================================
    # EVIDENCE
    # ========================================================

    print()
    print("EVIDENCE")

    if not result.evidence:

        print("  -")

    for index, item in enumerate(
        result.evidence,
        start=1,
    ):

        print()

        print(
            f"[{index}] "
            f"{item.title}"
        )

        print(
            f"    entity : "
            f"{item.entity}"
        )

        print(
            f"    score  : "
            f"{item.score}"
        )

        print(
            f"    type   : "
            f"{item.source_type.value}"
        )

        print(
            f"    url    : "
            f"{item.url}"
        )

        preview = (
            item.content[:180]
            .replace(
                "\n",
                " ",
            )
        )

        print(
            f"    text   : "
            f"{preview}..."
        )
