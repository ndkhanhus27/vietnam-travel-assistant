# Evaluation Runbook

## Prerequisites

Run from `D:\abc\backend`, using Python from `.venv`. Qdrant must be running
with a labeled corpus. The current version uses an entity-free collection;
set `QDRANT_COLLECTION=travel_chunks_no_entity_20261016` before running.
Configure models, API keys, and connections in `backend/.env`; never include
keys in reports or Git. Keep the dataset, corpus, and configuration fixed
throughout each evaluation run.

## Execution

Run each command separately; proceed only after the previous step completes.

```powershell
cd D:\abc\backend
$env:PYTHONIOENCODING = "utf-8"
$env:QDRANT_COLLECTION = "travel_chunks_no_entity_20261016"
$tag = Get-Date -Format "yyyyMMdd_HHmmss"
$workflow = "evaluation/reports/workflow_$tag.json"
$judge = "evaluation/reports/judge_$tag.json"

..\.venv\Scripts\python.exe -m evaluation.validate_dataset --qdrant-url http://localhost:6333
..\.venv\Scripts\python.exe -m evaluation.retrieval_benchmark --output "evaluation/reports/retrieval_$tag.json"
..\.venv\Scripts\python.exe -m evaluation.evaluate --approved-only --delay-seconds 15 --output $workflow
..\.venv\Scripts\python.exe -m evaluation.judge $workflow --output $judge --delay-seconds 5
```

- Retrieval benchmark: does not call Gemini or travel APIs; may download uncached models.
- Workflow: calls Gemini and tool APIs. The judge reads saved results without rerunning the chatbot.
- Judge: normally one Gemini call per case; failures and retries increase the call count.
- Retrieval-only configuration changes: run the separate benchmark; a workflow rerun is not mandatory.
  To make claims about answer quality under the new configuration, rerun both workflow and judge.

## Resuming and Interpreting Results

After an interruption, use the same output path and add `--resume` to the workflow
or judge command. The judge skips successfully scored cases; the workflow skips
all recorded cases, including failures. Do not change code, inputs, models, or
thresholds while resuming. If quota is exhausted, wait for it to recover;
investigate recurring format errors before making more calls.

A workflow is complete when `completed_at` is present and all selected cases
are recorded. The judge requires `judged_cases = selected_cases` and
`completed_at`. Its `quality_pass` indicates whether all four mean scores meet
the configured threshold, not the percentage of correct answers.

Recall@5 measures relevant-chunk recovery; MRR@10 measures the rank of the first
relevant chunk. Intent/tool metrics measure planning; success/degraded/error
measure execution. The judge scores correctness, relevance, groundedness, and
safety on a 1-5 scale, without citation scoring. Do not present new retrieval
measurements as end-to-end results of an older workflow.

Current results: [Evaluation report](reports/report_vi.md). Retain the original
JSON files for auditing; do not rerun completed evaluations merely to write reports.

## Completed Run

Workflow `workflow_no_entity_20261016_233751.json` and judge
`judge_no_entity_20261016_233751.json` completed all 110 cases on 17 October 2026
(Vietnam time). The report uses raw retrieval measured within this workflow;
the separate `retrieval_no_entity_retry.json` benchmark is used only to compare
rankings. Do not mix latency measurements from the two runs. No rerun is needed
to produce documentation.

One workflow case (`compound_015`) failed with Gemini 503 and remains in the
denominator. The judge recorded three transient scoring failures (one 503 and
two 429 responses), then completed; these are not additional workflow failures.
Workflow `--resume` also skips saved failed cases. To retry only the failed case,
use `--case-id compound_015` with a new output path; do not modify or replace
the original run's metrics. This retry still consumes real provider quota.
