# Evaluation

[Measured report](reports/report_vi.md) | [Run instructions](RUNBOOK.md).

## Scope

The dataset contains 110 questions in 10 categories, including 65 retrieval-labeled
cases. Evaluation covers planning, retrieval, execution, and answer quality.
Citation scoring and a dedicated guardrail suite are excluded.

## Latest Measured Run

Workflow and judge completed on 17 October 2026 (Vietnam time), using Gemini
3.5 Flash Lite and corpus-entity-free dense + BM25 + BGE reranking.
The BGE preset uses `BAAI/bge-reranker-v2-m3`, revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, CPU INT8,
10 candidates, hybrid limit 12, and rerank limit 6.

On 110 cases: intent accuracy 90.91%, tool exact match 94.55%, workflow success
97.27% (including degraded), degraded 36.36%, and errors 0.91%.
Judge averages: correctness 4.57, relevance 4.59, groundedness 4.78, safety 5.00.
All 110 cases were judged, including one workflow failure caused by Gemini 503.
The same model generated and judged the answers; scores are not independent
verification.

Raw retrieval within this workflow: Recall@5 83.08%, MRR@10 0.6173 for hybrid
+ BGE, with zero retrieval errors across 65 cases. This supersedes the old
82.31% BGE/entity benchmark as the current measurement, not as proof of
end-to-end improvement. See the [report](reports/report_vi.md) for latency,
baseline differences, and limitations, and the
[transition instructions](../../deploy/ENTITY-RETIREMENT.md) before EC2 changes.

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
..\.venv\Scripts\python.exe -m evaluation.export_report evaluation/reports/workflow_no_entity_20261016_233751.json --output-dir evaluation/reports/export
```

Workflow exports do not contain judge scores; retain the separate judge report.
