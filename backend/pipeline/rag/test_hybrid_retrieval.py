from __future__ import annotations

import argparse

from pipeline.rag.hybrid_retriever import (
    HybridRetriever,
)


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "query",
        nargs="+",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    query = " ".join(
        args.query
    ).strip()

    print()
    print("=" * 90)
    print(
        "STEP 6B - HYBRID RETRIEVAL"
    )
    print("=" * 90)

    print(
        f"Query: {query}"
    )

    print("=" * 90)
    print()

    retriever = (
        HybridRetriever()
    )

    results = retriever.search(
        query,
        limit=args.limit,
    )

    for rank, item in enumerate(
        results,
        start=1,
    ):

        preview = (
            item.content
            .replace(
                "\n",
                " ",
            )
            [:500]
        )

        print(
            f"[{rank}] "
            f"hybrid="
            f"{item.hybrid_score:.6f}"
        )

        print(
            f"    title       : "
            f"{item.title}"
        )

        print(
            f"    chunk       : "
            f"{item.chunk_index}"
        )

        print(
            f"    dense       : "
            f"rank={item.dense_rank} "
            f"score={item.dense_score}"
        )

        print(
            f"    bm25        : "
            f"rank={item.bm25_rank} "
            f"score={item.bm25_score}"
        )

        print(
            f"    entity      : "
            f"rank={item.entity_rank}"
        )

        print(
            f"    primary     : "
            f"{item.primary_entities}"
        )

        print(
            f"    text        : "
            f"{preview}"
        )

        print()


if __name__ == "__main__":
    main()