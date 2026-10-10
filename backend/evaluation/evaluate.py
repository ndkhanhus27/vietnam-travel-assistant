from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from evaluation.metrics import (
    percentile,
    precision_recall_f1,
    recall_at_k,
    reciprocal_rank,
    safe_div,
)
from evaluation.validate_dataset import read_jsonl, validate_records


EVALUATION_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = EVALUATION_DIR / "dataset.jsonl"
DEFAULT_REPORT = EVALUATION_DIR / "reports" / "evaluation_report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the real travel-agent workflow over the eval dataset.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--category")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--approved-only", action="store_true")
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.resume and args.output is None:
        parser.error("--resume requires --output pointing to the previous report")
    if not math.isfinite(args.delay_seconds) or args.delay_seconds < 0:
        parser.error("--delay-seconds must be finite and non-negative")
    return args


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_cases(path: Path) -> list[dict[str, Any]]:
    records, errors = read_jsonl(path)
    errors.extend(validate_records(records))
    if errors:
        details = "\n".join(f"  - {error}" for error in errors)
        raise ValueError(f"Dataset validation failed:\n{details}")
    return [
        {key: value for key, value in record.items() if key != "__line__"}
        for record in records
        if record.get("review_status") != "rejected"
    ]


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def model_to_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def unique_strings(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value)
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def retrieved_point_ids(evidence: Iterable[Any]) -> list[str]:
    point_ids: list[Any] = []
    for item in evidence:
        source_type = enum_value(getattr(item, "source_type", None))
        metadata = getattr(item, "metadata", {}) or {}
        point_id = metadata.get("point_id")
        if source_type == "rag" and point_id:
            point_ids.append(point_id)
    return unique_strings(point_ids)


def citation_checks(
    citations: Iterable[Any],
    *,
    evidence: Iterable[Any],
    observations: Iterable[Any],
) -> list[bool]:
    evidence_ids = {
        str(getattr(item, "evidence_id"))
        for item in evidence
        if getattr(item, "evidence_id", None)
    }
    task_ids = {
        str(getattr(item, "task_id"))
        for item in observations
        if getattr(item, "task_id", None)
    }
    checks: list[bool] = []
    for citation in citations:
        evidence_id = getattr(citation, "evidence_id", None)
        task_id = getattr(citation, "task_id", None)
        if evidence_id is not None:
            checks.append(str(evidence_id) in evidence_ids)
        elif task_id is not None:
            checks.append(str(task_id) in task_ids)
        else:
            checks.append(False)
    return checks


def empty_result(case: dict[str, Any]) -> dict[str, Any]:
    expected_tools = set(case["expected_tools"])
    return {
        "id": case["id"],
        "query": case["query"],
        "category": case["category"],
        "expected": {
            "intent": case["expected_intent"],
            "tools": sorted(expected_tools),
            "retrieval_mode": case["expected_retrieval_mode"],
            "relevant_chunk_ids": case["relevant_chunk_ids"],
            "requires_citations": case["requires_citations"],
        },
        "actual": {
            "intent": None,
            "tools": [],
            "retrieval_mode": None,
        },
        "planner": {
            "intent_ok": False,
            "tools_ok": False,
            "mode_ok": False,
            "tool_tp": 0,
            "tool_fp": 0,
            "tool_fn": len(expected_tools),
        },
        "retrieval": {
            "retrieved_ids": [],
            "recall_at_5": None,
            "reciprocal_rank_at_10": None,
        },
        "workflow": {
            "success": False,
            "degraded": False,
            "validation_valid": None,
            "citation_required": case["requires_citations"],
            "citation_ok": not case["requires_citations"],
            "valid_citations": 0,
            "total_citations": 0,
        },
        "answer": "",
        "citations": [],
        "evidence": [],
        "observations": [],
        "warnings": [],
        "latency_ms": 0.0,
        "error": None,
    }


def evaluate_case(workflow: Any, case: dict[str, Any]) -> dict[str, Any]:
    result = empty_result(case)
    started = time.perf_counter()
    try:
        state = workflow.run_sync(case["query"])
        plan = state.get("plan")
        response = state.get("response")
        validation = state.get("validation")
        reasoner_output = state.get("reasoner_output")
        evidence = state.get("research_evidence", [])
        observations = state.get("observations", [])

        if plan is None:
            raise ValueError("Final workflow state has no plan")
        if response is None:
            raise ValueError("Final workflow state has no response")

        actual_intent = enum_value(plan.intent)
        actual_mode = enum_value(plan.retrieval_mode)
        actual_tools = {enum_value(task.tool) for task in plan.subtasks}
        expected_tools = set(case["expected_tools"])
        tool_tp = len(actual_tools & expected_tools)
        tool_fp = len(actual_tools - expected_tools)
        tool_fn = len(expected_tools - actual_tools)

        retrieved_ids = retrieved_point_ids(evidence)
        relevant_ids = case["relevant_chunk_ids"]
        citations = list(response.citations)
        citation_validity = citation_checks(
            citations,
            evidence=evidence,
            observations=observations,
        )
        valid_citations = sum(citation_validity)
        citation_required = bool(case["requires_citations"])
        citation_ok = not citation_required or valid_citations > 0

        degraded = bool(response.degraded) or bool(
            reasoner_output is not None and reasoner_output.degraded
        )
        validation_valid = (
            bool(validation.valid) if validation is not None else None
        )
        answer = response.answer or ""
        workflow_success = bool(
            answer.strip() and (validation_valid is True or degraded)
        )

        result["actual"] = {
            "intent": actual_intent,
            "tools": sorted(actual_tools),
            "retrieval_mode": actual_mode,
        }
        result["planner"] = {
            "intent_ok": actual_intent == case["expected_intent"],
            "tools_ok": actual_tools == expected_tools,
            "mode_ok": actual_mode == case["expected_retrieval_mode"],
            "tool_tp": tool_tp,
            "tool_fp": tool_fp,
            "tool_fn": tool_fn,
        }
        result["retrieval"] = {
            "retrieved_ids": retrieved_ids,
            "recall_at_5": (
                recall_at_k(relevant_ids, retrieved_ids, k=5)
                if relevant_ids
                else None
            ),
            "reciprocal_rank_at_10": (
                reciprocal_rank(relevant_ids, retrieved_ids, k=10)
                if relevant_ids
                else None
            ),
        }
        result["workflow"] = {
            "success": workflow_success,
            "degraded": degraded,
            "validation_valid": validation_valid,
            "citation_required": citation_required,
            "citation_ok": citation_ok,
            "valid_citations": valid_citations,
            "total_citations": len(citations),
        }
        result["answer"] = answer
        result["citations"] = [model_to_json(item) for item in citations]
        result["evidence"] = [model_to_json(item) for item in evidence]
        result["observations"] = [model_to_json(item) for item in observations]
        result["warnings"] = (
            list(reasoner_output.warnings) if reasoner_output is not None else []
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["latency_ms"] = round(
            (time.perf_counter() - started) * 1000.0,
            2,
        )
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    cases = len(results)
    intent_ok = sum(item["planner"]["intent_ok"] for item in results)
    mode_ok = sum(item["planner"]["mode_ok"] for item in results)
    tools_ok = sum(item["planner"]["tools_ok"] for item in results)
    tool_tp = sum(item["planner"]["tool_tp"] for item in results)
    tool_fp = sum(item["planner"]["tool_fp"] for item in results)
    tool_fn = sum(item["planner"]["tool_fn"] for item in results)
    tool_metrics = precision_recall_f1(tp=tool_tp, fp=tool_fp, fn=tool_fn)

    retrieval_results = [
        item for item in results if item["expected"]["relevant_chunk_ids"]
    ]
    required_results = [
        item for item in results if item["workflow"]["citation_required"]
    ]
    total_citations = sum(
        item["workflow"]["total_citations"] for item in results
    )
    valid_citations = sum(
        item["workflow"]["valid_citations"] for item in results
    )
    latencies = [item["latency_ms"] for item in results]

    return {
        "planner": {
            "intent_accuracy": safe_div(intent_ok, cases),
            "retrieval_mode_accuracy": safe_div(mode_ok, cases),
            "tool_exact_match": safe_div(tools_ok, cases),
            "tool_precision": tool_metrics["precision"],
            "tool_recall": tool_metrics["recall"],
            "tool_f1": tool_metrics["f1"],
        },
        "retrieval": {
            "evaluated_cases": len(retrieval_results),
            "recall_at_5": safe_div(
                sum(
                    item["retrieval"]["recall_at_5"] or 0.0
                    for item in retrieval_results
                ),
                len(retrieval_results),
            ) if retrieval_results else None,
            "mrr_at_10": safe_div(
                sum(
                    item["retrieval"]["reciprocal_rank_at_10"] or 0.0
                    for item in retrieval_results
                ),
                len(retrieval_results),
            ) if retrieval_results else None,
        },
        "workflow": {
            "success_rate": safe_div(
                sum(item["workflow"]["success"] for item in results), cases
            ),
            "citation_required_pass_rate": safe_div(
                sum(
                    item["workflow"]["citation_ok"]
                    for item in required_results
                ),
                len(required_results),
            ) if required_results else None,
            "citation_validity_rate": safe_div(valid_citations, total_citations) if total_citations else None,
            "degraded_rate": safe_div(
                sum(item["workflow"]["degraded"] for item in results), cases
            ),
            "error_rate": safe_div(
                sum(item["error"] is not None for item in results), cases
            ),
        },
        "latency_ms": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
        },
    }


def summarize_by_category(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["category"]].append(result)
    return {
        category: {"cases": len(items), **summarize(items)}
        for category, items in sorted(grouped.items())
    }


def build_report(
    *,
    results: list[dict[str, Any]],
    started_at: str,
    completed_at: str | None,
    selected_cases: int,
) -> dict[str, Any]:
    return {
        "run": {
            "dataset": "evaluation/dataset.jsonl",
            "started_at": started_at,
            "completed_at": completed_at,
            "total_cases": len(results),
            "selected_cases": selected_cases,
        },
        "summary": summarize(results),
        "by_category": summarize_by_category(results),
        "cases": results,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_resume_report(path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot resume: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cannot resume invalid report: {exc}") from exc
    return (
        report.get("run", {}).get("started_at") or utc_now(),
        list(report.get("cases", [])),
    )


def selection_hash(cases: list[dict[str, Any]]) -> str:
    payload = json.dumps(cases, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_resume(report: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    if report.get("run", {}).get("selection_sha256") != selection_hash(cases):
        raise ValueError("Cannot resume: dataset or case selection changed; use a new output.")
    ids = [item["id"] for item in report.get("cases", [])]
    selected = {case["id"] for case in cases}
    if len(ids) != len(set(ids)) or not set(ids).issubset(selected):
        raise ValueError("Cannot resume: unexpected or duplicate case IDs.")


def runtime_metadata() -> dict[str, Any]:
    from app.core import config as app_config
    import pipeline.agents.workflow
    from app.core.config import settings

    # Explicit allowlist: never serialize settings containing credentials.
    names = (
        "gemini_model", "rag_embedding_model", "rag_reranker_model",
        "rag_rerank_enabled", "rag_rerank_limit", "qdrant_collection",
        "rag_chunk_size", "rag_chunk_overlap",
        "rag_retrieve_limit", "rag_context_chunks", "rag_max_chunks_per_document",
        "rag_dense_candidates", "rag_bm25_candidates", "rag_hybrid_limit",
        "rag_rrf_k", "rag_rrf_dense_weight", "rag_rrf_bm25_weight",
        "rag_rrf_entity_weight", "rag_rerank_candidates",
        "rag_reranker_batch_size", "rag_reranker_max_length",
        "rag_reranker_cpu_int8",
        "rag_reranker_revision",
        "openweather_units", "openweather_language", "openweather_timeout_seconds",
        "goong_timeout_seconds", "goong_retry_backoff_seconds",
    )
    roots = [Path(app_config.__file__).parents[1], Path(pipeline.agents.workflow.__file__).parents[1]]
    digest = hashlib.sha256()
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            digest.update(f"{root.name}/{path.relative_to(root).as_posix()}\n".encode("utf-8"))
            digest.update(path.read_bytes())
    versions = {}
    for name in ("google-genai", "qdrant-client", "sentence-transformers", "torch", "langgraph"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "application_source_sha256": digest.hexdigest(),
        "evaluation_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "package_versions": versions,
        "config": {name: getattr(settings, name) for name in names},
    }


def print_summary(report: dict[str, Any]) -> None:
    summary = report["summary"]
    planner = summary["planner"]
    retrieval = summary["retrieval"]
    workflow = summary["workflow"]
    latency = summary["latency_ms"]

    def rate(value: float | None) -> str:
        return "N/A" if value is None else f"{value:.2%}"

    print("=" * 78)
    print("VIETNAM TRAVEL ADVISOR EVALUATION")
    print("=" * 78)
    print(f"Cases                     : {report['run']['total_cases']}")
    print(f"Intent Accuracy           : {planner['intent_accuracy']:.2%}")
    print(
        "Retrieval Mode Accuracy   : "
        f"{planner['retrieval_mode_accuracy']:.2%}"
    )
    print(f"Tool Exact Match          : {planner['tool_exact_match']:.2%}")
    print(
        "Tool Precision / Recall   : "
        f"{planner['tool_precision']:.2%} / {planner['tool_recall']:.2%}"
    )
    print(f"Tool F1                   : {planner['tool_f1']:.2%}")
    print(
        "Recall@5 / MRR@10         : "
        f"{rate(retrieval['recall_at_5'])} / {rate(retrieval['mrr_at_10'])}"
    )
    print(f"Workflow Success          : {workflow['success_rate']:.2%}")
    print(
        "Degraded / Error          : "
        f"{workflow['degraded_rate']:.2%} / {workflow['error_rate']:.2%}"
    )
    print(
        "Citation Required Pass    : "
        f"{rate(workflow['citation_required_pass_rate'])}"
    )
    print(
        "Citation Validity         : "
        f"{rate(workflow['citation_validity_rate'])}"
    )
    print(
        "Latency p50 / p95         : "
        f"{latency['p50']:.2f} / {latency['p95']:.2f} ms"
    )


def main() -> int:
    args = parse_args()
    try:
        cases = load_cases(args.dataset)
    except (OSError, ValueError) as exc:
        print(exc)
        return 1

    if args.approved_only:
        cases = [case for case in cases if case["review_status"] == "approved"]
    if args.category:
        cases = [case for case in cases if case["category"] == args.category]
    if args.case_id:
        requested = set(args.case_id)
        missing = requested - {case["id"] for case in cases}
        if missing:
            print(f"Unknown or filtered case IDs: {sorted(missing)}")
            return 1
        cases = [case for case in cases if case["id"] in requested]
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        print("No evaluation cases matched the requested filters.")
        return 1

    started_at = utc_now()
    output = args.output or (
        EVALUATION_DIR / "reports" / f"evaluation_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    )
    if output.exists() and not args.resume:
        print(f"Output already exists: {output}. Use --resume or a new path.")
        return 1
    metadata = {
        "dataset": str(args.dataset),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "selection_sha256": selection_hash(cases),
        "selected_ids": [case["id"] for case in cases],
        "approved_only": args.approved_only,
        "delay_seconds": args.delay_seconds,
        "metric_scope": "final_plan_and_aggregated_evidence; citations_are_id_checks",
        **runtime_metadata(),
    }
    results: list[dict[str, Any]] = []
    if args.resume:
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
            validate_resume(previous, cases)
            if previous["run"].get("config") != metadata["config"]:
                raise ValueError("Cannot resume: model/RAG config changed; use a new output.")
            if previous["run"].get("delay_seconds") != args.delay_seconds:
                raise ValueError("Cannot resume: pacing changed; use a new output.")
            for key in ("application_source_sha256", "evaluation_source_sha256", "package_versions"):
                if previous["run"].get(key) != metadata[key]:
                    raise ValueError(f"Cannot resume: {key} changed; use a new output.")
            started_at, results = load_resume_report(output)
        except ValueError as exc:
            print(exc)
            return 1
        except OSError as exc:
            print(f"Cannot resume: {exc}")
            return 1

    completed_ids = {item["id"] for item in results}
    pending = [case for case in cases if case["id"] not in completed_ids]
    workflow = None

    for index, case in enumerate(pending, 1):
        print(f"[{index}/{len(pending)}] {case['id']}: {case['query']}")
        try:
            if workflow is None:
                from pipeline.agents.workflow import build_workflow

                workflow = build_workflow()
            result = evaluate_case(workflow, case)
        except Exception as exc:
            result = empty_result(case)
            result["error"] = f"{type(exc).__name__}: {exc}"

        results.append(result)
        checkpoint = build_report(
            results=results,
            started_at=started_at,
            completed_at=None,
            selected_cases=len(cases),
        )
        checkpoint["run"].update(metadata)
        write_report(output, checkpoint)
        if result["error"]:
            print(f"  ERROR: {result['error']}")
        if index < len(pending) and args.delay_seconds:
            time.sleep(args.delay_seconds)

    report = build_report(
        results=results,
        started_at=started_at,
        completed_at=utc_now(),
        selected_cases=len(cases),
    )
    report["run"].update(metadata)
    write_report(output, report)
    print_summary(report)
    print(f"Report: {output}")
    print("Note: success includes degraded answers; citations check IDs, not entailment.")
    return 1 if any(item["error"] for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
