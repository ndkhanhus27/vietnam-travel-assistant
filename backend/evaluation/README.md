# Evaluation

Bộ dữ liệu có 120 câu, 11 nhóm; 65 câu có nhãn retrieval.
[Kết quả đã chạy](reports/report_vi.md).

## Chạy trên Docker local

Trong PowerShell tại thư mục repo, sau khi backend và Qdrant đã chạy:

```powershell
docker exec abc-backend-1 mkdir -p /home/app/evaluation
docker cp .\backend\evaluation\. abc-backend-1:/home/app/evaluation
docker exec -e PYTHONPATH=/home/app:/app -w /home/app abc-backend-1 python -m evaluation.validate_dataset --qdrant-url http://qdrant:6333
docker exec -e PYTHONPATH=/home/app:/app -w /home/app abc-backend-1 python -m evaluation.evaluate --approved-only --delay-seconds 15 --output /home/app/workflow.json
docker exec -e PYTHONPATH=/home/app:/app -w /home/app abc-backend-1 python -m evaluation.retrieval_benchmark --output /home/app/retrieval.json
docker cp abc-backend-1:/home/app/workflow.json .\backend\evaluation\reports\workflow.json
docker cp abc-backend-1:/home/app/retrieval.json .\backend\evaluation\reports\retrieval.json
```

Workflow dùng quota Gemini/API công cụ; retrieval không gọi các API này.
Chọn tên output mới mỗi lần. Để tiếp tục lượt workflow bị ngắt, dùng cùng
tham số và thêm `--resume`.

## Xuất báo cáo

Từ thư mục `backend`, dùng Python của virtual environment:

```bash
python -m evaluation.export_report evaluation/reports/workflow.json --output-dir evaluation/reports/latest --retrieval-report evaluation/reports/retrieval.json
```

Lệnh xuất Markdown, CSV và JSON. Workflow/retrieval phải cùng bộ câu hỏi,
code và cấu hình. Output sinh tự động được ignore; chỉ báo cáo ngắn được đưa
lên Git.

Recall@5/MRR@10 đo truy xuất; intent/tool metrics đo kế hoạch; completion và
citation ID chỉ kiểm tra vận hành/cấu trúc, không phải độ chính xác câu trả lời.
