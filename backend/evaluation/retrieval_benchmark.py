from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path
from typing import Any

from evaluation.evaluate import DEFAULT_DATASET, load_cases, runtime_metadata, utc_now, write_report
from evaluation.export_report import write_csv
from evaluation.metrics import percentile, recall_at_k, reciprocal_rank


VARIANTS = ("dense", "hybrid", "hybrid_reranker")


def score_ranking(gold: list[str], items: list[Any], elapsed_ms: float) -> dict[str, Any]:
    ids = [str(item.point_id) for item in items]
    return {
        "retrieved_ids": ids,
        "recall_at_5": recall_at_k(gold, ids, k=5),
        "rr_at_10": reciprocal_rank(gold, ids, k=10),
        "latency_ms": round(elapsed_ms, 2), "error": None,
    }


def summarize_rankings(results: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for variant in VARIANTS:
        rows = [item["variants"][variant] for item in results]
        n = len(rows)
        output[variant] = {
            "cases": n,
            "recall_at_5": sum(item["recall_at_5"] for item in rows) / n if n else None,
            "mrr_at_10": sum(item["rr_at_10"] for item in rows) / n if n else None,
            "errors": sum(item["error"] is not None for item in rows),
            "latency_p50_ms": percentile((item["latency_ms"] for item in rows), 50) if n else None,
        }
    return output


def evaluate_ranking_case(case: dict[str, Any], hybrid: Any, reranker: Any, candidate_limit: int) -> dict[str, Any]:
    result = {"id": case["id"], "query": case["query"], "category": case["category"],
              "gold_ids": case["relevant_chunk_ids"], "variants": {}}
    candidates = None
    hybrid_ms = 0.0
    for variant in VARIANTS:
        started = time.perf_counter()
        try:
            if variant == "dense":
                items = hybrid.dense.search(case["query"], limit=10)
            elif variant == "hybrid":
                candidates = hybrid.search(case["query"], limit=candidate_limit)
                items = candidates[:10]
            else:
                if candidates is None:
                    raise RuntimeError("Hybrid retrieval failed; no candidates to rerank")
                items = reranker.rerank(query=case["query"], candidates=candidates, limit=10)
            elapsed = (time.perf_counter() - started) * 1000
            if variant == "hybrid":
                hybrid_ms = elapsed
            if variant == "hybrid_reranker":
                elapsed += hybrid_ms
            result["variants"][variant] = score_ranking(case["relevant_chunk_ids"], items, elapsed)
        except Exception as exc:
            result["variants"][variant] = {
                "retrieved_ids": [], "recall_at_5": 0.0, "rr_at_10": 0.0,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "error": f"{type(exc).__name__}: {exc}",
            }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate raw retrieval rankings without Gemini or web API calls.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".csv").exists():
        parser.error("Output exists; use a new path")
    cases = [case for case in load_cases(args.dataset) if case["review_status"] == "approved" and case["relevant_chunk_ids"]]
    if not cases:
        parser.error("No approved cases with gold chunk IDs")
    from app.core.config import settings
    from pipeline.rag.hybrid_retriever import HybridRetriever
    from pipeline.rag.reranker import TravelReranker

    metadata = runtime_metadata()
    hybrid = HybridRetriever()
    reranker = TravelReranker(retriever=hybrid)
    candidate_limit = max(10, settings.rag_rerank_candidates)
    run = {
        "started_at": utc_now(), "completed_at": None, "selected_cases": len(cases),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "benchmark_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "raw ranked chunks, before tool filtering and evidence aggregation",
        "query_input": "original dataset query; no gold entities supplied",
        "ranking_cutoff": 10, "reranker_candidates": candidate_limit,
        "corpus_points": hybrid.dense.client.count(hybrid.dense.collection_name, exact=True).count,
        "latency_note": "Model initialization excluded; sequential queries. Reranker time includes reused hybrid retrieval time.",
        **metadata,
    }
    results = []
    for index, case in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {case['id']}", flush=True)
        results.append(evaluate_ranking_case(case, hybrid, reranker, candidate_limit))
        write_report(args.output, {"run": run, "summary": summarize_rankings(results), "cases": results})
    run["completed_at"] = utc_now()
    write_report(args.output, {"run": run, "summary": summarize_rankings(results), "cases": results})
    rows = [{"id": case["id"], "category": case["category"], "variant": variant,
             "recall_at_5": case["variants"][variant]["recall_at_5"],
             "rr_at_10": case["variants"][variant]["rr_at_10"],
             "latency_ms": case["variants"][variant]["latency_ms"],
             "error": case["variants"][variant]["error"]}
            for case in results for variant in VARIANTS]
    write_csv(args.output.with_suffix(".csv"), list(rows[0]), rows)
    print(summarize_rankings(results))
    print(f"Report: {args.output}")
    return int(any(item["variants"][variant]["error"] for item in results for variant in VARIANTS))


if __name__ == "__main__":
    raise SystemExit(main())
