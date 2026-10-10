from __future__ import annotations

import argparse
import csv
import json
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from evaluation.evaluate import summarize
from evaluation.metrics import percentile, precision_recall_f1


def ratio(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def audited_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    legacy = summarize(cases)
    n = len(cases)
    retrieval = [item for item in cases if item["expected"]["relevant_chunk_ids"]]
    required = [item for item in cases if item["workflow"]["citation_required"]]
    citations = sum(item["workflow"]["total_citations"] for item in cases)
    labels = sorted(
        {item["expected"]["intent"] for item in cases}
        | {item["actual"]["intent"] for item in cases if item["actual"]["intent"]}
    )
    per_intent = {}
    for label in labels:
        tp = sum(item["expected"]["intent"] == label == item["actual"]["intent"] for item in cases)
        fp = sum(item["expected"]["intent"] != label == item["actual"]["intent"] for item in cases)
        fn = sum(item["actual"]["intent"] != label == item["expected"]["intent"] for item in cases)
        per_intent[label] = {
            **precision_recall_f1(tp=tp, fp=fp, fn=fn),
            "support": tp + fn,
        }
    clean = sum(
        bool(item["answer"].strip())
        and item["workflow"]["validation_valid"] is True
        and not item["workflow"]["degraded"]
        and item["error"] is None
        for item in cases
    )
    return {
        "cases": n,
        "planner": {
            **legacy["planner"],
            "intent_macro_f1": ratio(sum(item["f1"] for item in per_intent.values()), len(labels)),
            "per_intent": per_intent,
        },
        "evidence_proxy": {
            "eligible_cases": len(retrieval),
            "recall_at_5": ratio(sum(item["retrieval"]["recall_at_5"] or 0 for item in retrieval), len(retrieval)),
            "mrr_at_10": ratio(sum(item["retrieval"]["reciprocal_rank_at_10"] or 0 for item in retrieval), len(retrieval)),
            "max_retained_rag_ids": max((len(item["retrieval"]["retrieved_ids"]) for item in cases), default=0),
        },
        "operations": {
            "legacy_completion_rate": ratio(sum(item["workflow"]["success"] for item in cases), n),
            "nondegraded_validated_completion_count": clean,
            "nondegraded_validated_completion_rate": ratio(clean, n),
            "degraded_count": sum(item["workflow"]["degraded"] for item in cases),
            "error_count": sum(item["error"] is not None for item in cases),
            "degraded_rate": ratio(sum(item["workflow"]["degraded"] for item in cases), n),
            "error_rate": ratio(sum(item["error"] is not None for item in cases), n),
        },
        "citation_structure": {
            "required_cases": len(required),
            "required_pass_count": sum(item["workflow"]["citation_ok"] for item in required),
            "required_pass_rate": ratio(sum(item["workflow"]["citation_ok"] for item in required), len(required)),
            "total_citations": citations,
            "valid_ids": sum(item["workflow"]["valid_citations"] for item in cases),
            "valid_id_rate": ratio(sum(item["workflow"]["valid_citations"] for item in cases), citations),
        },
        "latency_ms": {
            "all_cases_p50": percentile((item["latency_ms"] for item in cases), 50) if cases else None,
            "all_cases_p95": percentile((item["latency_ms"] for item in cases), 95) if cases else None,
        },
        "semantic_quality": {
            "answer_correctness": None,
            "faithfulness": None,
            "citation_precision": None,
            "citation_recall": None,
            "note": "Not measured. Requires claim-level source checking or calibrated judges.",
        },
    }


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            # Answers and queries are untrusted text when opened in a spreadsheet.
            writer.writerow({
                key: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value
                for key, value in row.items()
            })


def percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2%}"


def test_summary(paths: list[Path]) -> list[dict[str, Any]]:
    output = []
    for path in paths:
        cases = list(ET.parse(path).getroot().iter("testcase"))
        if not cases:
            raise ValueError(f"No test cases recorded in {path}")
        failed = sum(case.find("failure") is not None or case.find("error") is not None for case in cases)
        skipped = sum(case.find("skipped") is not None for case in cases)
        output.append({"file": path.name, "total": len(cases), "passed": len(cases) - failed - skipped, "failed": failed, "skipped": skipped})
    return output


def brief_report(report: dict[str, Any], summary: dict[str, Any], software: list[dict[str, Any]] | None = None, environment: dict[str, Any] | None = None, retrieval_report: dict[str, Any] | None = None) -> str:
    run = report["run"]
    planner = summary["planner"]
    evidence = summary["evidence_proxy"]
    operations = summary["operations"]
    citations = summary["citation_structure"]
    latency = summary["latency_ms"]
    timestamp = run.get("started_at")
    date = "không ghi nhận"
    if timestamp:
        try:
            parsed = datetime.fromisoformat(timestamp)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            date = parsed.astimezone(timezone(timedelta(hours=7))).strftime("%d/%m/%Y %H:%M (giờ Việt Nam)")
        except (TypeError, ValueError):
            pass
    def seconds(value: float | None) -> str:
        return "N/A" if value is None else f"{value / 1000:.2f} giây"

    rows = [
        ("Intent accuracy", percent(planner["intent_accuracy"])),
        ("Intent macro-F1", percent(planner["intent_macro_f1"])),
        ("Retrieval-mode accuracy", percent(planner["retrieval_mode_accuracy"])),
        ("Tool-set exact match", percent(planner["tool_exact_match"])),
        ("Tool micro Precision / Recall / F1", " / ".join(percent(planner[key]) for key in ("tool_precision", "tool_recall", "tool_f1"))),
        *([] if retrieval_report else [
            ("Recall@5 của bằng chứng cuối", percent(evidence["recall_at_5"])),
            ("MRR@10 của bằng chứng cuối", "N/A" if evidence["mrr_at_10"] is None else f"{evidence['mrr_at_10']:.4f}"),
        ]),
        ("Hoàn tất qua validator, không degraded", percent(operations["nondegraded_validated_completion_rate"])),
        ("Tỷ lệ lỗi / degraded", f"{percent(operations['error_rate'])} / {percent(operations['degraded_rate'])}"),
        ("Citation ID tồn tại", f"{citations['valid_ids']}/{citations['total_citations']} ({percent(citations['valid_id_rate'])})"),
        ("Latency P50 / P95", f"{seconds(latency['all_cases_p50'])} / {seconds(latency['all_cases_p95'])}"),
    ]
    lines = [
        "# Kết quả evaluation", "",
        f"- Thời điểm bắt đầu: {date}.",
        f"- Dữ liệu: {summary['cases']}/{run.get('selected_cases', summary['cases'])} câu đã chạy, {len({item['category'] for item in report['cases']})} nhóm; {evidence['eligible_cases']} câu có nhãn chunk để đo retrieval.",
        "", "| Chỉ số | Kết quả |", "|---|---|",
        *[f"| {label} | {value} |" for label, value in rows], "",
        *(["### Retrieval độc lập", "",
           f"{retrieval_report['run']['selected_cases']} câu có gold chunk; cùng query gốc, corpus {retrieval_report['run']['corpus_points']} chunk, không dùng gold entity. Reranker xét {retrieval_report['run']['reranker_candidates']} ứng viên.",
           "", "| Phương pháp | Recall@5 | MRR@10 | Lỗi |", "|---|---:|---:|---:|",
           *[f"| {dict(dense='Dense', hybrid='Hybrid', hybrid_reranker='Hybrid + reranker').get(name, name)} | {percent(values['recall_at_5'])} | {values['mrr_at_10']:.4f} | {values['errors']} |" for name, values in retrieval_report["summary"].items()], ""] if retrieval_report else []),
        f"Lỗi: {operations['error_count']} câu; degraded: {operations['degraded_count']} câu.",
        "", "## Giới hạn", "",
        ("Retrieval đo top-k thô; nhãn chunk có thể chưa đầy đủ. " if retrieval_report else "Retrieval đo bằng chứng sau tổng hợp, không phải top-k thô. ") + "Completion không phải độ chính xác câu trả lời. Citation ID hợp lệ không chứng minh nguồn hỗ trợ nội dung. Chưa chấm correctness/faithfulness độc lập; latency không gồm HTTP/UI và không phải load test.",
    ]
    if software:
        lines.extend([
            "", "## Kiểm thử phần mềm", "",
            "| Bộ test | Passed | Failed | Skipped |", "|---|---:|---:|---:|",
            *[f"| {item['file']} | {item['passed']} | {item['failed']} | {item['skipped']} |" for item in software],
            "", "Regression dùng dịch vụ test riêng; Google/SMTP/workflow được mock. Browser test kiểm tra layout.",
            *([f"Frontend production build: {environment['frontend_build']}."] if environment and environment.get("frontend_build") else []),
        ])
    if not run.get("completed_at") or summary["cases"] != run.get("selected_cases", summary["cases"]):
        lines.extend(["", "**Lần chạy chưa hoàn tất; chưa dùng làm kết quả cuối.**"])
    return "\n".join(lines) + "\n"


def export_report(source: Path, destination: Path, test_reports: list[Path] | None = None, environment_path: Path | None = None, retrieval_path: Path | None = None) -> list[Path]:
    report = json.loads(source.read_text(encoding="utf-8"))
    cases = report["cases"]
    if not cases:
        raise ValueError("No completed cases to export")
    if len({item["id"] for item in cases}) != len(cases):
        raise ValueError("Duplicate case IDs in report")
    destination.mkdir(parents=True, exist_ok=True)
    paths = [destination / name for name in (
        "summary.json", "summary.md", "cases.csv", "categories.csv",
        "intent_confusion.csv", "manual_review.csv", "report_vi.md",
    )]
    if any(path.exists() for path in paths):
        raise ValueError("Export files already exist; select a new output directory to protect annotations.")
    summary = audited_summary(cases)
    software = test_summary(test_reports or [])
    environment = json.loads(environment_path.read_text(encoding="utf-8")) if environment_path else None
    retrieval_report = json.loads(retrieval_path.read_text(encoding="utf-8")) if retrieval_path else None
    if retrieval_report:
        expected_ids = {item["id"] for item in cases if item["expected"]["relevant_chunk_ids"]}
        retrieved_ids = [item["id"] for item in retrieval_report["cases"]]
        if not retrieval_report["run"].get("completed_at") or len(retrieved_ids) != len(set(retrieved_ids)) or set(retrieved_ids) != expected_ids:
            raise ValueError("Retrieval benchmark is incomplete or uses different cases")
        for key in ("dataset_sha256", "application_source_sha256", "config"):
            if report["run"].get(key) is None or report["run"][key] != retrieval_report["run"].get(key):
                raise ValueError(f"Retrieval benchmark has incompatible {key}")
    paths[6].write_text(brief_report(report, summary, software, environment, retrieval_report), encoding="utf-8")
    grouped = {
        category: audited_summary([item for item in cases if item["category"] == category])
        for category in sorted({item["category"] for item in cases})
    }
    paths[0].write_text(json.dumps({
        "source_report": str(source), "run": report["run"],
        "summary": summary, "by_category": grouped,
        "software_tests": software,
        "environment": environment,
        "retrieval_benchmark": retrieval_report,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    planner = summary["planner"]
    evidence = summary["evidence_proxy"]
    operations = summary["operations"]
    structure = summary["citation_structure"]
    metrics = [
        ("Intent accuracy", percent(planner["intent_accuracy"]), len(cases)),
        ("Intent macro-F1 (labels present in this run)", percent(planner["intent_macro_f1"]), len(cases)),
        ("Retrieval-mode accuracy", percent(planner["retrieval_mode_accuracy"]), len(cases)),
        ("Planned tool-set exact match", percent(planner["tool_exact_match"]), len(cases)),
        ("Planned tool micro precision / recall / F1", " / ".join(percent(planner[key]) for key in ("tool_precision", "tool_recall", "tool_f1")), "TP/FP/FN summed across cases"),
        ("Final-evidence Recall@5 / MRR@10 (proxy)", f"{percent(evidence['recall_at_5'])} / {percent(evidence['mrr_at_10'])}", evidence["eligible_cases"]),
        ("Legacy completion (includes degraded)", percent(operations["legacy_completion_rate"]), len(cases)),
        ("Nondegraded internally validated completion", percent(operations["nondegraded_validated_completion_rate"]), len(cases)),
        ("Degraded / error rate", f"{percent(operations['degraded_rate'])} / {percent(operations['error_rate'])}", len(cases)),
        ("Required cases with >=1 valid citation ID", percent(structure["required_pass_rate"]), structure["required_cases"]),
        ("Citation ID existence", percent(structure["valid_id_rate"]), structure["total_citations"]),
    ]
    lines = [
        "# Evaluation results", "",
        f"Source: `{source.name}`",
        f"Started (UTC): {report['run'].get('started_at', 'unknown')}",
        f"Completed (UTC): {report['run'].get('completed_at') or 'incomplete'}",
        f"Cases: {len(cases)} / {report['run'].get('selected_cases', 'unknown')}", "",
        "These numbers belong to the recorded run, not necessarily the current deployed version.", "",
        "| Metric | Result | Denominator / population |", "|---|---|---|",
        *[f"| {label} | {value} | {denominator} |" for label, value, denominator in metrics], "",
    ]
    for key, value in summary["latency_ms"].items():
        lines.append(f"- {key}: {'N/A' if value is None else f'{value / 1000:.3f} s'}")
    lines.extend([
        "", "## Interpretation limits", "",
        "- Final evidence is filtered, deduplicated and balanced; it is not raw retriever top-k ranking.",
        f"- Maximum retained RAG IDs in this run: {evidence['max_retained_rag_ids']}.",
        "- Citation ID existence does not measure semantic support, accuracy or citation completeness.",
        "- Neither completion definition is externally judged answer correctness.",
        "- No reference answers, claim-level correctness or human ratings are available automatically.",
        "- Latency covers run_sync, not HTTP/browser rendering; workflow construction is outside the timer.",
        "- Failures remain in denominators; missing gold labels are excluded only from retrieval metrics.",
        "- Five cases are a smoke test, not a representative benchmark or a stable p95 estimate.",
        "- Legacy runs without config/hash metadata cannot establish reproducible current-version performance.",
        "", "## Errors by type", "",
    ])
    errors = Counter(item["error"].split(":", 1)[0] for item in cases if item["error"])
    lines.extend([f"- {kind}: {count}" for kind, count in sorted(errors.items())] or ["- None recorded."])
    paths[1].write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = [{
        "id": item["id"], "category": item["category"], "query": item["query"],
        "expected_intent": item["expected"]["intent"], "actual_intent": item["actual"]["intent"],
        "intent_ok": item["planner"]["intent_ok"],
        "expected_tools": ";".join(item["expected"]["tools"]),
        "actual_planned_tools": ";".join(item["actual"]["tools"]),
        "tool_exact_match": item["planner"]["tools_ok"],
        "retrieval_eligible": bool(item["expected"]["relevant_chunk_ids"]),
        "final_evidence_recall_at_5": item["retrieval"]["recall_at_5"],
        "final_evidence_rr_at_10": item["retrieval"]["reciprocal_rank_at_10"],
        "legacy_completion": item["workflow"]["success"],
        "degraded": item["workflow"]["degraded"], "validation_valid": item["workflow"]["validation_valid"],
        "latency_ms": item["latency_ms"], "error": item["error"], "answer": item["answer"],
    } for item in cases]
    write_csv(paths[2], list(rows[0]) if rows else ["id"], rows)
    category_rows = [{
        "category": category, "cases": values["cases"],
        "intent_accuracy": values["planner"]["intent_accuracy"],
        "tool_f1": values["planner"]["tool_f1"],
        "retrieval_cases": values["evidence_proxy"]["eligible_cases"],
        "evidence_recall_at_5": values["evidence_proxy"]["recall_at_5"],
        "error_rate": values["operations"]["error_rate"],
    } for category, values in grouped.items()]
    write_csv(paths[3], list(category_rows[0]) if category_rows else ["category"], category_rows)
    confusion = Counter((item["expected"]["intent"], item["actual"]["intent"] or "<missing>") for item in cases)
    write_csv(paths[4], ["expected_intent", "actual_intent", "count"], [
        {"expected_intent": expected, "actual_intent": actual, "count": count}
        for (expected, actual), count in sorted(confusion.items())
    ])
    manual_rows = [{
        "id": item["id"], "category": item["category"], "query": item["query"],
        "answer": item["answer"],
        "citations_json": json.dumps(item["citations"], ensure_ascii=False),
        "evidence_json": json.dumps(item.get("evidence", []), ensure_ascii=False),
        "observations_json": json.dumps(item.get("observations", []), ensure_ascii=False),
        "rater": "", "reference_answer": "", "reference_sources": "",
        "correctness_0_2": "", "relevance_0_2": "", "completeness_0_2": "",
        "constraint_following_0_2": "", "verifiable_claims": "",
        "supported_claims": "", "claims_requiring_citation": "",
        "claims_with_supporting_citations": "", "citation_links_checked": "",
        "citation_links_supporting_claim": "", "task_success_0_1": "", "notes": "",
    } for item in cases]
    write_csv(paths[5], list(manual_rows[0]) if manual_rows else ["id"], manual_rows)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Export evaluation without LLM calls.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--test-report", type=Path, action="append", default=[])
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--retrieval-report", type=Path)
    args = parser.parse_args()
    try:
        paths = export_report(args.report, args.output_dir, args.test_report, args.environment, args.retrieval_report)
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        parser.exit(1, f"Export failed: {exc}\n")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
