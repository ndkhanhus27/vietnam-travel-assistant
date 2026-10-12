# Evaluation

[Báo cáo kết quả](reports/report_vi.md) | [Hướng dẫn chạy](RUNBOOK.md).

## Phạm vi

Dataset gồm 110 câu thuộc 10 nhóm, trong đó 65 câu có nhãn truy xuất.
Đánh giá bao gồm lập kế hoạch, truy xuất, vận hành và chất lượng trả lời.
Không chấm citation và không chạy bộ guardrail riêng.

Cấu hình BGE: `BAAI/bge-reranker-v2-m3`, revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, CPU INT8,
10 ứng viên, hybrid limit 12, rerank limit 6. Benchmark ngày 12/10/2026
đạt Recall@5 82,31%; kết quả này không thay thế workflow đã chạy với mMARCO.

## CI và staging

CI thông thường chạy unit, integration, contract, component, streaming và
browser tests với agent được mock, không gọi LLM thật. Browser tests giữ
các ranh giới HTTP, SQL, auth và SSE qua `tests.e2e_app`.

Workflow `Staging AI evaluation` chạy 50 câu được duyệt với model thật,
sau đó dùng Gemini judge chấm correctness, relevance, groundedness và safety.
Đây là tập con, không thay thế đánh giá đầy đủ 110 câu. Deployment production
theo workflow staging thay vì CI trực tiếp.

Thiết lập secrets trong GitHub environment `staging`: `GEMINI_API_KEY`,
`TAVILY_API_KEY`, `OPENWEATHER_API_KEY`, `GOONG_API_KEY`,
`STAGING_QDRANT_URL`, `LANGSMITH_API_KEY`. Biến repository
`STAGING_EVAL_ENABLED=true` bật gate tự động cho nhánh main.

## Lưu kết quả

JSON và CSV sinh tự động được ignore; giữ ở local để đối chiếu.
Chỉ đưa báo cáo ngắn và hướng dẫn vào Git. Xuất thêm bảng từ report có sẵn
(không gọi Gemini), chạy tại thư mục `backend`:

```powershell
..\.venv\Scripts\python.exe -m evaluation.export_report evaluation/reports/full_20261012_203925.json --output-dir evaluation/reports/export
```

Export workflow không chứa điểm judge; đối chiếu file judge riêng.
