# Kết quả evaluation

Ngày chạy: 10/10/2026, Docker local. Bộ câu hỏi gồm 120 câu, 11 nhóm;
65 câu có nhãn retrieval, corpus gồm 287 chunks.

## Workflow, 120 câu

| Chỉ số | Kết quả |
|---|---:|
| Intent accuracy | 88,33% |
| Intent macro-F1 | 90,90% |
| Retrieval-mode accuracy | 96,67% |
| Tool-set exact match | 95,83% |
| Tool micro-F1 | 97,66% |
| Hoàn tất qua validator, không degraded | 82,50% |
| Lỗi / degraded | 1 / 19 câu |
| Citation ID tồn tại | 241/241 |
| Latency P50 / P95 | 9,62 / 22,16 giây |

## Retrieval, 65 câu

| Phương pháp | Recall@5 | MRR@10 |
|---|---:|---:|
| Dense | 66,92% | 0,5535 |
| Hybrid | 74,62% | 0,6197 |
| Hybrid + reranker | 79,23% | 0,6321 |

Retrieval đo query gốc, không cung cấp gold entity; reranker xét 10 ứng viên.
Workflow và retrieval là các lượt chạy riêng. Chưa chạy lại full workflow
trên cấu hình retrieval hiện tại.

Kiểm thử phần mềm: backend 70, frontend 37, browser 33 test đều pass.
API regression mock Google/SMTP/workflow; browser test kiểm tra layout.

## Giới hạn

Validator và citation ID hợp lệ không chứng minh câu trả lời đúng hoặc nguồn
hỗ trợ nội dung. Chưa chấm correctness/faithfulness độc lập. Nhãn chunk có thể
chưa đầy đủ; latency không gồm HTTP/UI và không phải load test.
