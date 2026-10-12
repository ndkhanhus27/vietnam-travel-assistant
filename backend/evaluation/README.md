# Evaluation

## CI and staging quality gates

Pull requests and normal pushes run deterministic unit, integration, contract,
component, streaming, and browser tests. They never call a paid LLM. The browser
suite uses `tests.e2e_app`, which keeps real HTTP, SQL, auth, and SSE boundaries
while replacing only the agent workflow.

`Staging AI evaluation` is the only workflow that calls the real model. It runs
50 approved golden cases, scores correctness, relevance, groundedness, and
safety with a LangSmith-traced Gemini judge, then runs the prompt-injection
dataset. Production deployment follows this workflow instead of CI directly.

Configure the `staging` GitHub environment with `GEMINI_API_KEY`,
`TAVILY_API_KEY`, `OPENWEATHER_API_KEY`, `GOONG_API_KEY`,
`STAGING_QDRANT_URL`, and `LANGSMITH_API_KEY`. Set repository variable
`STAGING_EVAL_ENABLED=true` to enable the automatic main-branch gate.

Bộ dữ liệu có 110 câu, 10 nhóm; 65 câu yêu cầu RAG và có nhãn chunk.
[Kết quả đã chạy](reports/report_vi.md).

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
55 câu chỉ dùng web/công cụ/trả lời trực tiếp không tính vào điểm retrieval.
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

Recall@5/MRR@10 đo truy xuất; intent/tool metrics đo kế hoạch; completion và
citation ID chỉ kiểm tra vận hành/cấu trúc, không phải độ chính xác câu trả lời.

## Cách tính

- Recall@5: số chunk đúng trong top 5 / tổng chunk đúng của câu; lấy trung bình 65 câu.
- MRR@10: trung bình nghịch đảo vị trí chunk đúng đầu tiên trong top 10; không tìm thấy tính 0.
- Dense, Hybrid và Hybrid + reranker dùng cùng query và corpus; reranker dùng ứng viên Hybrid, không nhận nhãn đúng.
- Workflow chạy cả 110 câu: intent accuracy/macro-F1, tool exact match/micro-F1, tỷ lệ lỗi/degraded, latency P50/P95.
- Lỗi giữ trong mẫu số; 55 câu không yêu cầu RAG ghi N/A cho retrieval, không tính 0.
- Cố định bộ nhãn/cấu hình trước khi chạy; không chỉnh tham số theo kết quả rồi gọi đó là kiểm chứng độc lập.
- Chỉ báo cáo full khi số câu đã chạy bằng số câu được chọn và có `completed_at`; lưu JSON gốc để đối chiếu.
