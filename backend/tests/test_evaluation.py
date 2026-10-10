from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evaluation.evaluate import (
    build_report, citation_checks, empty_result, parse_args, selection_hash, summarize,
    validate_resume,
    evaluate_complete_case,
    daily_quota_exhausted,
)
from evaluation.export_report import audited_summary, brief_report, export_report
from evaluation.metrics import percentile, precision_recall_f1, recall_at_k, reciprocal_rank
from evaluation.retrieval_benchmark import evaluate_ranking_case, score_ranking, summarize_rankings
from evaluation.validate_dataset import requires_rag, validate_records


def sample_case() -> dict:
    return {
        "id": "sample", "query": "Example question", "category": "factual",
        "expected_intent": "FACTUAL_TRAVEL", "expected_tools": ["search_travel_knowledge"],
        "expected_retrieval_mode": "RAG_FIRST", "relevant_chunk_ids": ["gold"],
        "requires_citations": True, "review_status": "approved",
    }


class EvaluationTest(unittest.TestCase):
    def test_daily_quota_detection_does_not_stop_on_other_errors(self):
        self.assertTrue(daily_quota_exhausted({"error": "429 GenerateRequestsPerDayPerProjectPerModel-FreeTier"}))
        self.assertFalse(daily_quota_exhausted({"error": "429 requests per minute"}))
        self.assertFalse(daily_quota_exhausted({"error": None}))

    def test_rag_scope_uses_expected_tool_not_mixed_mode_or_category(self):
        case = sample_case()
        self.assertTrue(requires_rag(case))
        case.update(category="compound", expected_retrieval_mode="MIXED", expected_tools=["routing", "weather"])
        self.assertFalse(requires_rag(case))
        self.assertFalse(requires_rag({"expected_tools": 42}))

    def test_approved_rag_case_without_gold_is_rejected(self):
        case = {**sample_case(), "entities": [], "notes": "", "relevant_chunk_ids": [], "__line__": 1}
        self.assertTrue(any("RAG case must have" in error for error in validate_records([case])))
        case["expected_tools"] = ["weather"]
        self.assertFalse(any("RAG case must have" in error for error in validate_records([case])))

    def test_non_rag_case_runs_workflow_without_loading_retriever(self):
        case = {**sample_case(), "expected_tools": ["weather"], "relevant_chunk_ids": []}
        workflow = object()
        with patch("evaluation.evaluate.evaluate_case", return_value=empty_result(case)) as evaluate:
            result = evaluate_complete_case(workflow, case)
        evaluate.assert_called_once_with(workflow, case)
        self.assertIsNone(result["raw_retrieval"])
        report = build_report(results=[result], started_at="now", completed_at="now", selected_cases=1)
        self.assertEqual(report["summary"]["coverage"], {"workflow_cases": 1, "rag_cases": 0, "non_rag_cases": 1})
        self.assertIsNone(report["summary"]["raw_retrieval"]["hybrid_reranker"]["recall_at_5"])

    def test_rag_case_shares_workflow_model_and_keeps_raw_results(self):
        case = sample_case()
        hybrid = object()
        reranker = SimpleNamespace(retriever=hybrid)
        workflow = SimpleNamespace(executor=SimpleNamespace(registry=SimpleNamespace(knowledge=SimpleNamespace(retriever=reranker))))
        raw = {"id": case["id"], "variants": {}}
        with patch("evaluation.retrieval_benchmark.evaluate_ranking_case", return_value=raw) as rank, \
                patch("evaluation.evaluate.evaluate_case", return_value=empty_result(case)):
            result = evaluate_complete_case(workflow, case)
        self.assertIs(result["raw_retrieval"], raw)
        self.assertIs(rank.call_args.args[1], hybrid)
        self.assertIs(rank.call_args.args[2], reranker)

    def test_retrieval_initialization_failure_does_not_skip_workflow(self):
        case = sample_case()
        with patch("evaluation.evaluate.evaluate_case", return_value=empty_result(case)) as evaluate:
            result = evaluate_complete_case(object(), case)
        evaluate.assert_called_once()
        self.assertEqual(result["raw_retrieval"]["variants"]["hybrid_reranker"]["recall_at_5"], 0)
        self.assertIn("AttributeError", result["raw_retrieval"]["variants"]["hybrid_reranker"]["error"])

    def test_export_uses_retrieval_from_same_combined_run(self):
        case = sample_case()
        points = [SimpleNamespace(point_id="gold")]
        hybrid = SimpleNamespace(dense=SimpleNamespace(search=lambda query, limit: points), search=lambda query, limit: points)
        reranker = SimpleNamespace(rerank=lambda query, candidates, limit: points)
        result = empty_result(case)
        result["raw_retrieval"] = evaluate_ranking_case(case, hybrid, reranker, 10)
        report = build_report(results=[result], started_at="2026-10-10T10:00:00+00:00", completed_at="done", selected_cases=1)
        report["run"].update(dataset_sha256="dataset", application_source_sha256="code", config={}, corpus_points=1, reranker_candidates=10)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "combined.json"
            source.write_text(json.dumps(report), encoding="utf-8")
            output = Path(directory) / "export"
            export_report(source, output)
            text = (output / "report_vi.md").read_text(encoding="utf-8")
            self.assertIn("1 câu yêu cầu RAG; 0 câu không áp dụng", text)
            self.assertIn("Hybrid + reranker", text)
            self.assertNotIn("Model:", text)

    def test_incomplete_combined_export_is_marked_not_final(self):
        case = sample_case()
        result = empty_result(case)
        points = [SimpleNamespace(point_id="gold")]
        hybrid = SimpleNamespace(dense=SimpleNamespace(search=lambda query, limit: points), search=lambda query, limit: points)
        result["raw_retrieval"] = evaluate_ranking_case(case, hybrid, SimpleNamespace(rerank=lambda **kwargs: points), 10)
        report = build_report(results=[result], started_at="2026-10-11T00:00:00+00:00", completed_at=None, selected_cases=120)
        report["run"].update(dataset_sha256="dataset", application_source_sha256="code", config={}, corpus_points=1, reranker_candidates=10)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "partial.json"
            source.write_text(json.dumps(report), encoding="utf-8")
            destination = Path(directory) / "export"
            export_report(source, destination)
            self.assertIn("chưa hoàn tất", (destination / "report_vi.md").read_text(encoding="utf-8"))

    def test_non_rag_combined_export_has_no_raw_retrieval_table(self):
        case = sample_case()
        case.update(expected_tools=[], relevant_chunk_ids=[])
        result = empty_result(case)
        result["raw_retrieval"] = None
        report = build_report(results=[result], started_at="2026-10-11T00:00:00+00:00", completed_at="done", selected_cases=1)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "direct.json"
            source.write_text(json.dumps(report), encoding="utf-8")
            destination = Path(directory) / "export"
            export_report(source, destination)
            self.assertNotIn("Hybrid + reranker", (destination / "report_vi.md").read_text(encoding="utf-8"))
    def test_recall_deduplicates_relevant_hits(self):
        self.assertEqual(recall_at_k(["a", "b"], ["a", "a", "x"], k=5), 0.5)

    def test_raw_ranking_scores_point_ids(self):
        result = score_ranking(["gold"], [SimpleNamespace(point_id="x"), SimpleNamespace(point_id="gold")], 12)
        self.assertEqual(result["recall_at_5"], 1)
        self.assertEqual(result["rr_at_10"], 0.5)

    def test_reranker_latency_includes_hybrid_retrieval(self):
        points = [SimpleNamespace(point_id="gold"), SimpleNamespace(point_id="x")]
        hybrid = SimpleNamespace(dense=SimpleNamespace(search=lambda query, limit: points), search=lambda query, limit: points)
        reranker = SimpleNamespace(rerank=lambda query, candidates, limit: list(reversed(candidates)))
        with patch("evaluation.retrieval_benchmark.time.perf_counter", side_effect=[0, 1, 2, 5, 6, 10]):
            result = evaluate_ranking_case(sample_case(), hybrid, reranker, 20)
        self.assertEqual(result["variants"]["hybrid_reranker"]["latency_ms"], 7000)
        self.assertEqual(result["variants"]["hybrid_reranker"]["rr_at_10"], 0.5)

    def test_failed_retrieval_is_zero_and_remains_in_denominator(self):
        def fail(*args, **kwargs):
            raise RuntimeError("Unavailable")
        hybrid = SimpleNamespace(dense=SimpleNamespace(search=fail), search=fail)
        result = evaluate_ranking_case(sample_case(), hybrid, SimpleNamespace(rerank=fail), 20)
        summary = summarize_rankings([result])
        self.assertEqual(summary["hybrid"]["cases"], 1)
        self.assertEqual(summary["hybrid"]["errors"], 1)
        self.assertEqual(summary["hybrid"]["recall_at_5"], 0)

    def test_recall_respects_cutoff(self):
        self.assertEqual(recall_at_k(["a"], ["x", "a"], k=1), 0)

    def test_rr_uses_first_relevant_rank(self):
        self.assertEqual(reciprocal_rank(["a", "b"], ["x", "a", "b"], k=10), 0.5)

    def test_rr_miss_is_zero(self):
        self.assertEqual(reciprocal_rank(["a"], ["x"], k=10), 0)

    def test_micro_f1(self):
        self.assertAlmostEqual(precision_recall_f1(tp=2, fp=1, fn=2)["f1"], 4 / 7)

    def test_percentile_interpolates(self):
        self.assertAlmostEqual(percentile([10, 20, 30, 40], 95), 38.5)

    def test_missing_gold_is_not_zero_score(self):
        result = empty_result(sample_case())
        result["expected"]["relevant_chunk_ids"] = []
        summary = audited_summary([result])
        self.assertIsNone(summary["evidence_proxy"]["recall_at_5"])
        self.assertIsNone(summary["citation_structure"]["valid_id_rate"])
        self.assertIsNone(summarize([result])["retrieval"]["recall_at_5"])

    def test_cli_supports_separate_output_and_case_selection(self):
        with patch("sys.argv", ["evaluate", "--output", "smoke.json", "--case-id", "sample", "--approved-only"]):
            args = parse_args()
        self.assertEqual(args.output, Path("smoke.json"))
        self.assertEqual(args.case_id, ["sample"])
        self.assertTrue(args.approved_only)

    def test_cli_resume_requires_explicit_output(self):
        with patch("sys.argv", ["evaluate", "--resume"]), patch("sys.stderr"), self.assertRaises(SystemExit):
            parse_args()

    def test_cli_rejects_invalid_delay(self):
        for value in ("-1", "nan", "inf"):
            with self.subTest(value=value), patch("sys.argv", ["evaluate", "--delay-seconds", value]), patch("sys.stderr"), self.assertRaises(SystemExit):
                parse_args()

    def test_empty_report_cannot_export_fake_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "empty.json"
            source.write_text(json.dumps({"cases": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No completed"):
                export_report(source, Path(directory) / "export")

    def test_brief_report_uses_vietnam_time_and_marks_incomplete_run(self):
        result = empty_result(sample_case())
        report = build_report(results=[result], started_at="2026-10-10T17:30:00+00:00", completed_at=None, selected_cases=120)
        text = brief_report(report, audited_summary([result]))
        self.assertIn("11/10/2026 00:30", text)
        self.assertIn("1/120", text)
        self.assertIn("chưa hoàn tất", text)
        self.assertIn("không phải độ chính xác câu trả lời", text)

    def test_execution_failure_penalizes_retrieval(self):
        result = empty_result(sample_case())
        result["error"] = "TimeoutError"
        self.assertEqual(audited_summary([result])["evidence_proxy"]["recall_at_5"], 0)

    def test_degraded_is_not_clean_completion(self):
        result = empty_result(sample_case())
        result["answer"] = "Fallback answer"
        result["workflow"].update(success=True, degraded=True, validation_valid=True)
        summary = audited_summary([result])["operations"]
        self.assertEqual(summary["legacy_completion_rate"], 1)
        self.assertEqual(summary["nondegraded_validated_completion_rate"], 0)

    def test_macro_f1_penalizes_missing_prediction(self):
        result = empty_result(sample_case())
        self.assertEqual(audited_summary([result])["planner"]["intent_macro_f1"], 0)

    def test_citation_check_only_tests_id(self):
        checks = citation_checks(
            [SimpleNamespace(evidence_id="e1", task_id=None)],
            evidence=[SimpleNamespace(evidence_id="e1", content="Unrelated content")],
            observations=[],
        )
        self.assertEqual(checks, [True])

    def test_resume_rejects_changed_selection(self):
        with self.assertRaisesRegex(ValueError, "selection changed"):
            validate_resume({"run": {"selection_sha256": "different"}}, [sample_case()])

    def test_resume_rejects_duplicate_ids(self):
        cases = [sample_case()]
        report = {"run": {"selection_sha256": selection_hash(cases)}, "cases": [{"id": "sample"}] * 2}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_resume(report, cases)

    def test_resume_accepts_matching_selection(self):
        cases = [sample_case()]
        validate_resume({"run": {"selection_sha256": selection_hash(cases)}, "cases": [{"id": "sample"}]}, cases)

    def test_export_preserves_source_and_blank_human_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = build_report(results=[empty_result(sample_case())], started_at="old", completed_at="old", selected_cases=1)
            source = root / "source.json"
            source.write_text(json.dumps(report), encoding="utf-8")
            before = source.read_bytes()
            paths = export_report(source, root / "export")
            self.assertEqual(len(paths), 7)
            self.assertEqual(source.read_bytes(), before)
            with (root / "export/manual_review.csv").open(encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["correctness_0_2"], "")
            with self.assertRaisesRegex(ValueError, "already exist"):
                export_report(source, root / "export")


if __name__ == "__main__":
    unittest.main()
