# Kết quả evaluation

- Thời điểm chạy: 11/10/2026, Docker local.
- Dữ liệu: 120/120 câu, 11 nhóm; 65 câu yêu cầu RAG, 55 câu không áp dụng retrieval.

| Chỉ số workflow | Kết quả |
|---|---:|
| Intent accuracy | 91,67% |
| Intent macro-F1 | 93,42% |
| Retrieval-mode accuracy | 95,83% |
| Tool-set exact match | 95,00% |
| Tool micro-F1 | 97,25% |
| Hoàn tất qua validator, không degraded | 80,83% |
| Lỗi / degraded | 1 / 20 câu |
| Citation ID tồn tại | 251/251 |
| Latency P50 / P95 | 13,54 / 32,36 giây |

| Phương pháp retrieval | Recall@5 | MRR@10 | Lỗi |
|---|---:|---:|---:|
| Dense | 66,92% | 0,5535 | 0 |
| Hybrid | 74,62% | 0,6197 | 0 |
| Hybrid + reranker | 79,23% | 0,6321 | 0 |

Retrieval dùng query gốc trên 287 chunks; reranker xét 10 ứng viên. Lỗi workflow
thuộc `comparison_012`: mô hình sinh một evidence ID không tồn tại.

## Giới hạn

Recall/MRR phụ thuộc độ đầy đủ của nhãn chunk. Citation ID hợp lệ không chứng minh
nguồn hỗ trợ nội dung. Chưa chấm correctness/faithfulness độc lập; latency không
gồm HTTP/UI và không phải load test.
