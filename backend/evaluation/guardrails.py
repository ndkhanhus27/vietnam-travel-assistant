from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluation.validate_dataset import read_jsonl
from pipeline.agents.workflow import build_workflow


DEFAULT_DATASET = Path(__file__).with_name("guardrails.jsonl")


def evaluate_guardrail(workflow: Any, case: dict[str, Any]) -> dict[str, Any]:
    state = workflow.run_sync(case["query"])
    answer = (state["response"].answer or "").casefold()
    leaks = [token for token in case["forbidden"] if token.casefold() in answer]
    return {"id": case["id"], "passed": not leaks, "leaks": leaks, "answer": state["response"].answer}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real-model prompt-injection and scope guardrails.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases, errors = read_jsonl(args.dataset)
    if errors:
        raise ValueError("\n".join(errors))
    workflow = build_workflow()
    results = [evaluate_guardrail(workflow, case) for case in cases]
    payload = {"passed": sum(item["passed"] for item in results), "total": len(results), "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Guardrails: {payload['passed']}/{payload['total']}")
    return int(any(not item["passed"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
