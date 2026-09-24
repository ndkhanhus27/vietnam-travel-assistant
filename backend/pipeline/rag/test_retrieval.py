from __future__ import annotations

import argparse

from pipeline.rag.retriever import (
    DenseRetriever,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Test dense retrieval "
            "against Qdrant travel_chunks."
        )
    )

    parser.add_argument(
        "query",
        nargs="+",
        help="Câu hỏi cần retrieve.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Số chunks trả về.",
    )

    return parser.parse_args()


def print_result(
    *,
    rank: int,
    item,
) -> None:

    preview = (
        item.content
        .replace(
            "\n",
            " ",
        )
        .strip()
    )

    if len(preview) > 700:
        preview = (
            preview[:700]
            + "..."
        )

    print(
        f"[{rank}] "
        f"score={item.score:.4f}"
    )

    print(
        f"    title    : "
        f"{item.title}"
    )

    print(
        f"    chunk    : "
        f"{item.chunk_index}"
    )

    print(
        f"    primary  : "
        f"{item.primary_entities}"
    )

    print(
        f"    entities : "
        f"{item.entities[:10]}"
    )

    print(
        f"    source   : "
        f"{item.source_url}"
    )

    print(
        f"    text     : "
        f"{preview}"
    )

    print()


def main() -> None:
    args = parse_args()

    query = " ".join(
        args.query
    ).strip()

    print()
    print("=" * 78)
    print(
        "STEP 6 - DENSE RETRIEVAL TEST"
    )
    print("=" * 78)

    print(
        f"Query : {query}"
    )

    print(
        f"Top K : {args.limit}"
    )

    print("=" * 78)
    print()

    retriever = DenseRetriever()

    results = retriever.search(
        query,
        limit=args.limit,
    )

    if not results:
        print(
            "Không có kết quả."
        )
        return

    for rank, item in enumerate(
        results,
        start=1,
    ):
        print_result(
            rank=rank,
            item=item,
        )


if __name__ == "__main__":
    main()