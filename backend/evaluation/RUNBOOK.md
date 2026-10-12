# Hướng dẫn đánh giá

## Điều kiện

Chạy tại `D:\abc\backend`, dùng Python từ `.venv`. Qdrant phải hoạt động và có
corpus đã gán nhãn. Cấu hình model, API key và kết nối trong `backend/.env`;
không đưa key vào báo cáo hoặc Git. Giữ dataset, corpus và cấu hình cố định
trong mỗi lượt đánh giá.

## Các bước chạy

Chạy từng lệnh; chỉ chuyển bước khi bước trước đã hoàn tất.

```powershell
cd D:\abc\backend
$env:PYTHONIOENCODING = "utf-8"
$tag = Get-Date -Format "yyyyMMdd_HHmmss"
$workflow = "evaluation/reports/workflow_$tag.json"
$judge = "evaluation/reports/judge_$tag.json"

..\.venv\Scripts\python.exe -m evaluation.validate_dataset --qdrant-url http://localhost:6333
..\.venv\Scripts\python.exe -m evaluation.retrieval_benchmark --output "evaluation/reports/retrieval_$tag.json"
..\.venv\Scripts\python.exe -m evaluation.evaluate --approved-only --delay-seconds 15 --output $workflow
..\.venv\Scripts\python.exe -m evaluation.judge $workflow --output $judge --delay-seconds 5
```

- Retrieval benchmark: không gọi Gemini hoặc API du lịch; có thể tải model nếu chưa được cache.
- Workflow: gọi Gemini và các API công cụ; judge đọc kết quả đã lưu, không chạy lại chatbot.
- Judge: thông thường một lần gọi Gemini cho mỗi câu; lỗi và thử lại làm tăng số lần gọi.
- Chỉ đổi cấu hình retrieval: chạy benchmark riêng, không bắt buộc chạy lại workflow.
  Muốn kết luận chất lượng trả lời với cấu hình mới thì phải chạy lại workflow và judge.

## Tiếp tục và đọc kết quả

Khi gián đoạn, dùng đúng đường dẫn output và thêm `--resume` vào lệnh workflow
hoặc judge. Judge bỏ qua câu đã chấm thành công; workflow bỏ qua các câu đã ghi,
kể cả câu lỗi. Không sửa code, input, model hoặc ngưỡng khi resume. Nếu hết quota,
chờ quota hồi phục; lỗi định dạng lặp lại cần chẩn đoán trước khi gọi tiếp.

Workflow hoàn tất khi có `completed_at` và đủ số câu được chọn. Judge cần
`judged_cases = selected_cases` và `completed_at`; `quality_pass` cho biết cả bốn
điểm trung bình có đạt ngưỡng cấu hình hay không, không phải tỷ lệ câu đúng.

Recall@5 đo mức thu hồi chunk liên quan; MRR@10 đo thứ hạng chunk đúng đầu tiên.
Intent/tool metrics đo kế hoạch; success/degraded/error đo vận hành. Judge chấm
correctness, relevance, groundedness và safety theo thang 1–5, không chấm citation.
Không gộp số đo retrieval mới thành kết quả end-to-end của workflow cũ.

Kết quả hiện có: [Báo cáo đánh giá](reports/report_vi.md). Lưu JSON gốc để đối chiếu;
không cần chạy lại các lượt đã hoàn tất chỉ để viết báo cáo.
