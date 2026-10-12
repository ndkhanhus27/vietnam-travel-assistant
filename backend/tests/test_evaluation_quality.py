import json
import pytest

from evaluation.judge import AnswerScores, build_prompt, report_cases, run_judge


def test_answer_score_schema_rejects_values_outside_five_point_scale():
    scores = AnswerScores(correctness=5, relevance=4, groundedness=3, safety=5, reason="Grounded")
    assert scores.correctness == 5


def test_judge_prompt_contains_question_answer_and_tool_evidence():
    result = {
        "query": "Huế cuối tuần có mưa không?",
        "expected": {"intent": "WEATHER", "tools": ["weather"]},
        "answer": "Có khả năng mưa.",
        "evidence": [{"content": "Weather source data"}],
        "observations": [{"tool": "weather", "result": {"rain": True}}],
        "warnings": [],
    }
    prompt = build_prompt(result)
    assert result["query"] in prompt
    assert result["answer"] in prompt
    assert json.dumps(result["observations"], ensure_ascii=False) in prompt
    assert json.dumps(result["evidence"], ensure_ascii=False) in prompt


def test_judge_reads_cases_from_the_workflow_report_contract():
    cases = [{"id": "golden-001"}]
    assert report_cases({"cases": cases}) == cases


def workflow_report(tmp_path):
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps({
        "run": {"completed_at": "done", "selected_cases": 2, "config": {}},
        "cases": [{"id": "case-1"}, {"id": "case-2"}],
    }), encoding="utf-8")
    return path


def test_judge_checkpoint_survives_failure_and_resume_skips_scored_cases(tmp_path, monkeypatch):
    source = workflow_report(tmp_path)
    output = tmp_path / "judge.json"
    scores = AnswerScores(correctness=4, relevance=4, groundedness=4, safety=4, reason="Supported")

    def interrupted(runtime, case):
        if case["id"] == "case-2":
            raise RuntimeError("provider unavailable")
        return scores

    monkeypatch.setattr("evaluation.judge.judge_result", interrupted)
    assert run_judge(source, output, runtime=object(), delay_seconds=0) == 1
    partial = json.loads(output.read_text(encoding="utf-8"))
    assert partial["run"]["completed_at"] is None
    assert partial["quality_pass"] is None
    assert [row["id"] for row in partial["cases"]] == ["case-1"]

    calls = []

    def resumed(runtime, case):
        calls.append(case["id"])
        return scores

    monkeypatch.setattr("evaluation.judge.judge_result", resumed)
    assert run_judge(source, output, resume=True, runtime=object(), delay_seconds=0) == 0
    complete = json.loads(output.read_text(encoding="utf-8"))
    assert calls == ["case-2"]
    assert complete["run"]["judged_cases"] == 2
    assert complete["quality_pass"] is True
    assert len(complete["attempt_failures"]) == 1


def test_judge_prevents_overwrite_and_resume_with_different_report(tmp_path, monkeypatch):
    source = workflow_report(tmp_path)
    output = tmp_path / "judge.json"
    monkeypatch.setattr("evaluation.judge.judge_result", lambda *args: AnswerScores(
        correctness=4, relevance=4, groundedness=4, safety=4, reason="Supported"))
    run_judge(source, output, runtime=object(), delay_seconds=0)
    with pytest.raises(ValueError, match="Output exists"):
        run_judge(source, output, runtime=object(), delay_seconds=0)
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Cannot resume"):
        run_judge(source, output, resume=True, runtime=object(), delay_seconds=0)
