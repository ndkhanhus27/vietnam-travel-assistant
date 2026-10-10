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
)
from evaluation.export_report import audited_summary, brief_report, export_report
from evaluation.metrics import percentile, precision_recall_f1, recall_at_k, reciprocal_rank
from evaluation.retrieval_benchmark import evaluate_ranking_case, score_ranking, summarize_rankings


def sample_case() -> dict:
    return {
        "id": "sample", "query": "Example question", "category": "factual",
        "expected_intent": "FACTUAL_TRAVEL", "expected_tools": ["search_travel_knowledge"],
        "expected_retrieval_mode": "RAG_FIRST", "relevant_chunk_ids": ["gold"],
        "requires_citations": True, "review_status": "approved",
    }


class EvaluationTest(unittest.TestCase):
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
