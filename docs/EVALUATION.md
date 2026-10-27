# Đánh giá có provenance

Ba lớp khác nhau: pytest fixture kiểm tra toán học/contract; real smoke kiểm tra nối media/model/index/UI; benchmark relevance đo chất lượng bằng nhãn người kiểm duyệt. [smoke-real.json](reports/smoke-real.json) thuộc lớp thứ hai, không được dùng để tuyên bố Recall/MRR.

Trang Đánh giá xuất/lưu schema nhãn qua POST `/api/evaluation/labels`. Ví dụ đầy đủ ở `app.evaluation.LABEL_SCHEMA`. `provenance=human_reviewed`, split train/dev/test; mỗi query có event_id, video_uid, interval ms và grade0–4. Validator chặn overlap trong cùng video/query, ID trùng, end trước start và vượt duration. Xem video trước khi gán nhãn; không lấy rank1 làm ground truth tự động.

```powershell
.\.venv\Scripts\python.exe -m app.cli evaluate 'data\labels.json' --top-k 10 --output 'data\evaluation\report-human.json'
```

Recall@K ở mức event/query: số event relevant được hit / tổng event relevant đã gán nhãn. Một frame relevant thứ hai của cùng event không tăng hit/gain. Precision@K chia cho K, thiếu kết quả coi là slot không relevant. RR=1/rank đầu hit, MRR là trung bình RR theo query. DCG dùng `(2^grade-1)/log2(rank+1)`, nDCG chia ideal DCG từ các event. AP@K truncated, mAP@K chỉ xuất khi **mọi query** khai báo exhaustive_judgments=true; trường hợp khác là null/N/A. Các kết quả chưa được judge không tự thành ground truth âm đầy đủ; nếu chưa exhaustive chỉ dùng P/R theo nhãn hiện có, ghi rõ hạn chế coverage.

Không gộp query train/dev/test để chọn weights. Ablation: sao chép queries với mode visual_text/ocr/asr/hybrid/temporal và chạy cùng labels/split, cấu hình được ghi trong report. Nếu chưa có OCR/ASR/nhãn thì ghi N/A. Runner hiện giữ default weights, không có reranker học. Tune trên dev bằng search API/config riêng, test chỉ đo sau khi chốt.

Report chứa label_sha256, index_version, hardware/device, query_count, kết quả từng query, latency wall từ encoder đến retrieval/response service. Cold first báo riêng; warm p50/p95 trên các query sau; tổng p50/p95 gồm cold được đặt tên riêng. Đây không phải end-to-end network/browser/media latency hoặc một benchmark phần cứng đủ lớn. Với ba query smoke chỉ báo raw latency, không cam kết tốc độ. UI/browser seek và media request được kiểm tra riêng.

Chưa có nhãn thật tại thời điểm bàn giao, nên chưa có report quality benchmark cho kho 726 video. Với mode temporal, runner hiện đánh giá event anchor A; chưa có matcher/nhãn hai interval A/B để đánh giá semantic toàn sequence. Không dùng metric anchor để kết luận B đúng. Bài lab fixture có output riêng `docs/reports/labs.json`; không trộn report lab vào trang report dataset thật. Phân tích lỗi cần ghi query, video/mốc ground truth, keyframe thiếu, OCR/ASR sai, encoder language, merge/rerank và timestamp lệch trước khi tăng model.
