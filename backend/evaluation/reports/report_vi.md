# Báo cáo đánh giá Vietnam Travel Advisor

## Phạm vi và phương pháp

Đánh giá ngày 12/10/2026 trên Windows local, gồm 110 câu thuộc 10 nhóm;
65 câu có nhãn truy xuất, 45 câu không yêu cầu RAG. Corpus gồm 287 chunks.
Workflow sử dụng Gemini 3.5 Flash Lite và reranker mMARCO. Benchmark truy xuất
BGE được chạy riêng trên cùng dataset; không thay thế kết quả workflow cũ.

## Kết quả workflow và chất lượng trả lời

| Chỉ số | Kết quả |
|---|---:|
| Intent accuracy | 91,82% |
| Retrieval-mode accuracy | 95,45% |
| Tool-set exact match | 95,45% |
| Tool precision / recall / F1 | 98,23% / 95,69% / 96,94% |
| Workflow success (bao gồm degraded) | 97,27% |
| Degraded / error | 31,82% / 0,00% |
| Latency P50 / P95 | 11,30 / 23,97 giây |
| Judge: correctness | 4,65/5 |
| Judge: relevance | 4,63/5 |
| Judge: groundedness | 4,81/5 |
| Judge: safety | 5,00/5 |

Judge hoàn tất 110/110 câu; cả bốn điểm trung bình đạt ngưỡng 3,5/5.
Hai lần lỗi định dạng tại `routing_009` đã được ghi nhận; lượt chấm cuối hoàn tất.
Workflow success phản ánh vận hành, không đồng nghĩa với độ chính xác nội dung.

## Kết quả truy xuất riêng

| Phương pháp | Recall@5 | MRR@10 | Latency P50 |
|---|---:|---:|---:|
| Dense | 66,92% | 0,5536 | 0,236 giây |
| Hybrid | 77,69% | 0,6221 | 0,195 giây |
| Hybrid + BGE Reranker | 82,31% | 0,6189 | 8,455 giây |

Cả ba phương pháp đánh giá trên 65 câu, không có lỗi. BGE dùng
`BAAI/bge-reranker-v2-m3`, CPU INT8, 10 ứng viên và hybrid limit 12.
Recall@5 tăng 4,62 điểm phần trăm so với Hybrid, trong khi MRR@10 giảm nhẹ.
Độ trễ truy xuất không gồm khởi tạo mô hình và không phải độ trễ toàn hệ thống.

## Kết luận và giới hạn

BGE cải thiện khả năng thu hồi tài liệu liên quan trong top 5 nhưng tăng độ trễ.
Cần ưu tiên giảm degraded, đặc biệt nhóm thông tin hiện thời (12/12 câu) và
câu hỏi kết hợp (12/15 câu). Chưa đánh giá lại toàn bộ workflow với BGE.

Judge dùng cùng model với chatbot trong phạm vi dự án cá nhân; điểm có thể chịu
thiên lệch chung, chưa được kiểm chứng độc lập bởi con người. Điểm safety không
thay thế kiểm thử bảo mật hoặc prompt injection. Không chấm citation; không chạy
bộ guardrail riêng. Dataset hữu hạn, chưa chứng minh khả năng tổng quát hóa;
Recall/MRR phụ thuộc nhãn chunk. Kết quả không phải kiểm thử tải hay giao diện.

## Dữ liệu đối chiếu

- Workflow: `full_20261012_203925.json`.
- Judge của workflow trên: `judge_full_20261012_203925.json`.
- Benchmark truy xuất BGE: `retrieval_bge_20261012_220440.json`.

Các JSON gốc được lưu tại `backend/evaluation/reports/`, không đưa vào Git.
