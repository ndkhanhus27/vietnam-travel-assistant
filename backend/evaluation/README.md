# Evaluation

## CI and staging quality gates

Pull requests and normal pushes run deterministic unit, integration, contract,
component, streaming, and browser tests. They never call a paid LLM. The browser
suite uses `tests.e2e_app`, which keeps real HTTP, SQL, auth, and SSE boundaries
while replacing only the agent workflow.

`Staging AI evaluation` is the only workflow that calls the real model. It runs
50 approved golden cases, scores correctness, relevance, groundedness, and
safety with a LangSmith-traced Gemini judge. Production deployment follows
this workflow instead of CI directly. Citation checks and prompt-injection
guardrail tests are not part of evaluation.

Configure the `staging` GitHub environment with `GEMINI_API_KEY`,
`TAVILY_API_KEY`, `OPENWEATHER_API_KEY`, `GOONG_API_KEY`,
`STAGING_QDRANT_URL`, and `LANGSMITH_API_KEY`. Set repository variable
`STAGING_EVAL_ENABLED=true` to enable the automatic main-branch gate.

Bộ dữ liệu có 110 câu, 10 nhóm; 65 câu yêu cầu RAG và có nhãn chunk.
[Kết quả đã chạy](reports/report_vi.md).

## Cấu hình Hybrid + Reranker ưu tiên

`backend/.env` và `.env.example` dùng cấu hình của lượt 11/10/2026:
`BAAI/bge-reranker-v2-m3`, revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`,
CPU INT8, 10 ứng viên, hybrid limit 12 và rerank limit 6. Lượt cũ đạt
Recall@5 79,23% trên 65 câu RAG. Ba câu đã đổi sau khi bỏ budget, nên điểm
của dataset hiện tại phải được đo lại.

Chạy retrieval riêng trước; bước này không gọi Gemini hay các API travel:

```powershell
cd D:\abc\backend
$env:PYTHONIOENCODING = "utf-8"
$tag = Get-Date -Format "yyyyMMdd_HHmmss"
..\.venv\Scripts\python.exe -m evaluation.validate_dataset --qdrant-url http://localhost:6333
..\.venv\Scripts\python.exe -m evaluation.retrieval_benchmark --output "evaluation/reports/retrieval_bge_$tag.json"
```

Giữ cấu hình và corpus cố định khi chạy full workflow tiếp theo. Chạy bằng
tiến trình Python mới để đọc `.env`; nếu model revision chưa có trong cache,
lần đầu sẽ tải trọng số từ Hugging Face.

## Chạy lại toàn bộ từ đầu trên Windows

Từ PowerShell, dùng tên output mới để tách lần chạy với cơ chế nguồn tham khảo
do backend tạo. Không resume báo cáo của phiên bản cũ. Gemini chỉ viết nội dung;
backend tạo danh sách nguồn từ dữ liệu đã chọn, không chấm citation trong eval.

```powershell
cd D:\abc\backend
$env:PYTHONIOENCODING = "utf-8"
$runTag = Get-Date -Format "yyyyMMdd_HHmmss"
$workflowPath = "evaluation/reports/workflow_backend_sources_$runTag.json"
$judgePath = "evaluation/reports/judge_backend_sources_$runTag.json"
$exportDir = "evaluation/reports/export_backend_sources_$runTag"

..\.venv\Scripts\python.exe -m evaluation.validate_dataset --qdrant-url http://localhost:6333
..\.venv\Scripts\python.exe -m evaluation.evaluate --approved-only --delay-seconds 15 --output $workflowPath
..\.venv\Scripts\python.exe -m evaluation.judge $workflowPath --output $judgePath --delay-seconds 5
..\.venv\Scripts\python.exe -m evaluation.export_report $workflowPath --output-dir $exportDir
```

Chạy từng lệnh và kiểm tra kết quả trước khi qua bước tiếp theo. Dataset phải
validate thành công, workflow phải hoàn tất 110/110 câu trước khi chạy judge.
Nếu lần workflow mới bị ngắt, giữ nguyên `$workflowPath` và chạy lại lệnh
`evaluation.evaluate` với `--resume`. Khi hết quota ngày, chờ quota hồi phục.
Judge dùng Gemini thật và điểm quality nằm trong file `$judgePath`; bản export
workflow chỉ tổng hợp planner, retrieval, completion và latency.

Judge lưu checkpoint sau mỗi câu và dừng khi provider lỗi. Tiếp tục bằng cùng
lệnh judge với `--resume`; các câu đã chấm thành công sẽ không bị gọi lại.
Giữ nguyên file workflow, code judge, model và ngưỡng điểm khi resume. Không
thay model giữa một lượt chấm. File judge ghi model, tiến độ và giới hạn đánh
giá tự động dùng cùng model trong phạm vi project cá nhân.

## Chạy trên Docker local

Trong PowerShell tại thư mục repo, sau khi backend và Qdrant đã chạy:

```powershell
docker exec abc-backend-1 mkdir -p /home/app/evaluation
docker cp .\backend\evaluation\. abc-backend-1:/home/app/evaluation
docker exec -e PYTHONPATH=/home/app:/app -w /home/app abc-backend-1 python -m evaluation.validate_dataset --qdrant-url http://qdrant:6333
docker exec -e PYTHONPATH=/home/app:/app -w /home/app abc-backend-1 python -m evaluation.evaluate --approved-only --delay-seconds 15 --output /home/app/workflow.json
docker cp abc-backend-1:/home/app/workflow.json .\backend\evaluation\reports\workflow.json
```

Một lượt chạy workflow đủ 110 câu và đo retrieval cho 65 câu yêu cầu RAG.
45 câu chỉ dùng web/công cụ/trả lời trực tiếp không tính vào điểm retrieval.
Nếu câu yêu cầu RAG thiếu nhãn chunk, validator báo lỗi thay vì bỏ qua.
Workflow dùng quota Gemini/API công cụ; phần retrieval không gọi các API này.
Chọn tên output mới mỗi lần. Để tiếp tục lượt workflow bị ngắt, dùng cùng
tham số và thêm `--resume`. Các lỗi đã ghi vẫn giữ trong kết quả, không tự chạy lại.
Khi hết quota ngày, chương trình lưu checkpoint và dừng; chưa coi là kết quả full.

## Xuất báo cáo

Từ thư mục `backend`, dùng Python của virtual environment:

```bash
python -m evaluation.export_report evaluation/reports/workflow.json --output-dir evaluation/reports/latest
```

Lệnh xuất Markdown, CSV và JSON từ cùng lượt retrieval + workflow.
Output sinh tự động được ignore; chỉ báo cáo ngắn được đưa
lên Git.

Recall@5/MRR@10 đo truy xuất; intent/tool metrics đo kế hoạch; completion
đo vận hành, không phải độ chính xác câu trả lời. Judge chấm correctness,
relevance, groundedness và safety từ câu trả lời, evidence và tool observations.

Dataset không cần trường `requires_citations`. Giữ nguyên câu hỏi và các nhãn
`expected_intent`, `expected_tools`, `expected_retrieval_mode`, `entities`,
`category`, `relevant_chunk_ids`, `notes`, `review_status` để đo phần còn lại.

## Cách tính

- Recall@5: số chunk đúng trong top 5 / tổng chunk đúng của câu; lấy trung bình 65 câu.
- MRR@10: trung bình nghịch đảo vị trí chunk đúng đầu tiên trong top 10; không tìm thấy tính 0.
- Dense, Hybrid và Hybrid + reranker dùng cùng query và corpus; reranker dùng ứng viên Hybrid, không nhận nhãn đúng.
- Workflow chạy cả 110 câu: intent accuracy/macro-F1, tool exact match/micro-F1, tỷ lệ lỗi/degraded, latency P50/P95.
- Lỗi giữ trong mẫu số; 45 câu không yêu cầu RAG ghi N/A cho retrieval, không tính 0.
- Cố định bộ nhãn/cấu hình trước khi chạy; không chỉnh tham số theo kết quả rồi gọi đó là kiểm chứng độc lập.
- Chỉ báo cáo full khi số câu đã chạy bằng số câu được chọn và có `completed_at`; lưu JSON gốc để đối chiếu.
