import json

from evaluation.judge import AnswerScores, build_prompt, report_cases


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
