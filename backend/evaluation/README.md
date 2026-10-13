# Evaluation

[Measured report](reports/report_vi.md) | [Run instructions](RUNBOOK.md).

## Scope

The dataset contains 110 questions in 10 categories, including 65 retrieval-labeled
cases. Evaluation covers planning, retrieval, execution, and answer quality.
Citation scoring and a dedicated guardrail suite are excluded.

The BGE preset uses `BAAI/bge-reranker-v2-m3`, revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, CPU INT8,
10 candidates, hybrid limit 12, and rerank limit 6. The 12 October 2026 benchmark
achieved Recall@5 of 82.31%; it does not replace the completed mMARCO workflow.

## CI and Staging

Normal CI runs unit, integration, contract, component, streaming, and browser
tests with a mocked agent, without live LLM calls. Browser tests retain HTTP,
SQL, authentication, and SSE boundaries through `tests.e2e_app`.

`Staging AI evaluation` runs the first 50 approved cases with the real model
and a Gemini judge for correctness, relevance, groundedness, and safety.
This subset does not replace the full 110-case evaluation. Automatic deployment
follows successful staging, not CI directly.

Configure GitHub environment `staging` secrets: `GEMINI_API_KEY`,
`TAVILY_API_KEY`, `OPENWEATHER_API_KEY`, `GOONG_API_KEY`,
`STAGING_QDRANT_URL`, and `LANGSMITH_API_KEY`. Repository variable
`STAGING_EVAL_ENABLED=true` enables the automatic main-branch gate.

## Report Storage

Generated JSON and CSV files remain ignored and local for auditing.
Commit only the concise report and instructions. To export an existing workflow
without calling Gemini, run from `backend`:

```powershell
..\.venv\Scripts\python.exe -m evaluation.export_report evaluation/reports/full_20261012_203925.json --output-dir evaluation/reports/export
```

Workflow exports do not contain judge scores; retain the separate judge report.
