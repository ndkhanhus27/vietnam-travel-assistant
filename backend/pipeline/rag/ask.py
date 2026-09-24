from __future__ import annotations

import argparse

from pipeline.rag.rag_service import (
    RagService,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Ask the Vietnam Travel RAG."
    )

    parser.add_argument(
        "question",
        nargs="+",
        help="Câu hỏi cần hỏi.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    question = " ".join(
        args.question
    ).strip()

    print()
    print("=" * 78)
    print("VIETNAM TRAVEL RAG")
    print("=" * 78)

    print(
        f"Question: {question}"
    )

    print("=" * 78)
    print()

    service = RagService()

    response = service.answer(
        question
    )

    print("ANSWER")
    print("-" * 78)
    print(response.answer)

    print()
    print("SOURCES")
    print("-" * 78)

    if not response.sources:
        print(
            "Không có nguồn."
        )

        return

    for source in response.sources:
        print(
            f"[{source.source_id}] "
            f"{source.title}"
        )

        print(
            f"    score : "
            f"{source.score:.4f}"
        )

        print(
            f"    chunk : "
            f"{source.chunk_index}"
        )

        print(
            f"    url   : "
            f"{source.source_url}"
        )


if __name__ == "__main__":
    main()