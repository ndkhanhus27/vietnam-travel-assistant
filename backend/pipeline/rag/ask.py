from __future__ import annotations

import argparse

from pipeline.rag.rag_service import TravelRAGService


def parse_args():
    parser = argparse.ArgumentParser(
        description="Vietnam Travel Hybrid RAG"
    )

    parser.add_argument(
        "question",
        nargs="+",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    question = " ".join(args.question).strip()

    print()
    print("=" * 90)
    print("STEP 8 - VIETNAM TRAVEL RAG")
    print("=" * 90)

    print(f"Question: {question}")

    print("=" * 90)
    print()

    service = TravelRAGService()
    result = service.answer(question)

    # ============================================================
    # ANSWER
    # ============================================================

    print("ANSWER")
    print("-" * 90)

    print(result.answer)

    # ============================================================
    # SOURCES
    # ============================================================

    print()
    print("SOURCES")
    print("-" * 90)

    if not result.sources:
        print("Không có source.")

    else:
        for source in result.sources:
            print(f"[{source.source_id}] {source.title}")
            print(f"    rerank : {source.rerank_score:.6f}")
            print(f"    hybrid : {source.hybrid_score:.6f}")
            print(f"    chunk  : {source.chunk_index}")
            print(f"    url    : {source.source_url}")

    # ============================================================
    # VALIDATION
    # ============================================================

    print()
    print("VALIDATION")
    print("-" * 90)

    print(f"Evidence valid : {result.evidence_validation.valid}")

    if result.evidence_validation.issues:
        print("Evidence issues:")

        for issue in result.evidence_validation.issues:
            print(f"  - {issue}")

    if result.citation_validation is not None:
        print(f"Citation valid : {result.citation_validation.valid}")
        print(f"Citations      : {result.citation_validation.citations}")

        if result.citation_validation.issues:
            print("Citation issues:")

            for issue in result.citation_validation.issues:
                print(f"  - {issue}")

    print(f"Needs research  : {result.needs_research}")


if __name__ == "__main__":
    main()
