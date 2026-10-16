# Vietnam Travel Advisor Evaluation Report

## Scope and Configuration

The workflow ran from 23:37 on 16 October to 01:33 on 17 October 2026;
judging completed at 02:39 on 17 October 2026 (Vietnam time).
Evaluation ran locally on Windows: 110 questions in 10 categories,
including 65 retrieval-labeled cases and 45 non-RAG cases; the corpus contains 287 chunks.

Configuration: Gemini 3.5 Flash Lite; dense BGE-M3 + title/content BM25,
weighted RRF, and `BAAI/bge-reranker-v2-m3` with CPU INT8, 10 candidates,
hybrid limit 12, and rerank limit 6. Collection: `travel_chunks_no_entity_20261016`.
Corpus-extracted entities are not used; place names identified from user queries
are retained. Reasoner and synthesizer remain separate LLM stages.

## Workflow and Answer Quality

| Metric | Result |
|---|---:|
| Intent accuracy | 90.91% |
| Retrieval-mode accuracy | 95.45% |
| Tool-set exact match | 94.55% |
| Tool precision / recall / F1 | 97.35% / 94.83% / 96.07% |
| Workflow success, including degraded answers | 97.27% (107/110) |
| Degraded | 36.36% (40/110) |
| Error | 0.91% (1/110) |
| Workflow latency P50 / P95 | 38.81 / 64.37 s |
| Judge: correctness / relevance | 4.57 / 4.59 out of 5 |
| Judge: groundedness / safety | 4.78 / 5.00 out of 5 |

The judge completed 110/110 cases; all four mean scores met the 3.5/5 threshold.
Success and degraded are not mutually exclusive; success does not imply complete
factual correctness. The two unsuccessful cases other than the 503 failure also
remain in the denominator of 110.

Case `compound_015` failed with Gemini 503 due to model overload and is retained
in the results. The judge recorded one 503 at `routing_004` and two 429 responses
at `compound_007`, then completed. Transient judging failures are not counted
as additional workflow failures. All 12 current_info cases and 11/15 compound
cases were degraded. These remain priority limitations, not resolved issues.

## Retrieval Within the Same Workflow Run

| Method | Recall@5 | MRR@10 | Latency P50 |
|---|---:|---:|---:|
| Dense | 66.92% | 0.5536 | 0.311 s |
| Hybrid: Dense + BM25 | 74.62% | 0.5778 | 0.261 s |
| Hybrid + BGE Reranker | 83.08% | 0.6173 | 12.685 s |

Each method was measured on 65 cases with zero retrieval errors. These are raw
rankings using original queries, before tool filtering and evidence aggregation;
the ranking measurement does not call Gemini. Timings exclude model initialization
and pacing delays; they are not end-to-end system latency.

The workflow's final-evidence proxy is Recall@5 = 36.15%, MRR@10 = 0.4000.
This measures the chunk list remaining after workflow processing, not raw retrieval.

## Comparison and Interpretation

Compared with the 12 October BGE benchmark using corpus entities, final Recall@5
increased from 82.31% to 83.08% (+0.77 percentage points), while MRR@10 decreased
slightly from 0.6189 to 0.6173. Hybrid without reranking decreased from 77.69%
to 74.62%. This small difference on a finite dataset does not establish a
statistically significant improvement.

The old workflow used mMARCO; the new workflow uses BGE and removes corpus
entities, so this is not a single-factor experiment. Success remains 97.27%;
degraded increased from 31.82% to 36.36%, and latency P50/P95 increased from
11.30/23.97 to 38.81/64.37 s. Do not attribute all changes to entity removal;
models, external APIs, retries, and local machine load also affect the results.

The separate `retrieval_no_entity_retry.json` benchmark has the same aggregate
Recall/MRR, but records collection `travel_chunks`, not the workflow's collection
name. The new code ignores corpus entity metadata even in the old collection.
This report uses raw retrieval measured within the new workflow to avoid mixing
metadata and latency from different runs.

## Limitations and Source Reports

The judge uses the same Gemini 3.5 Flash Lite model as the chatbot within a
personal-project scope; shared biases are possible, and there is no independent
human verification. Citation scoring and a dedicated guardrail suite are excluded.
Safety scores do not replace security testing. The dataset and chunk labels are
finite; these results do not establish generalization, concurrent-load capacity,
or UI quality. Local evaluation does not verify the version deployed on EC2.

- Workflow and raw retrieval: `workflow_no_entity_20261016_233751.json`.
- Judge for that workflow: `judge_no_entity_20261016_233751.json`; the source SHA-256 was verified to match.
- Separate benchmark: `retrieval_no_entity_retry.json`.
- Historical baseline: `full_20261012_203925.json`,
  `judge_full_20261012_203925.json`, `retrieval_bge_20261012_220440.json`.

Original JSON reports remain local in `backend/evaluation/reports/`, outside Git.
Do not delete failed-run reports or rejudge to replace a published run's metrics.
