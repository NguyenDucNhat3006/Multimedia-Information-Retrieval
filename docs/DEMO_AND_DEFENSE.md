# Kịch bản demo và bảo vệ

1. Chạy doctor, mở trang Dữ liệu: giải thích2 video/72 keyframe là subset smoke; OCR/ASR chưa có. Chỉ vào index_version và provenance report.
2. Thị giác: tìm `a television news presenter`; nói query được tokenize và encode bằng cùng OpenCLIP space ảnh. Score cosine không là xác suất. Xem nhiều frame rồi chọn một mốc.
3. Player: kiểm tra video name và ms, seek về đúng giây; timeline chọn trước/sau. Giải thích keyframe ordinal khác original_frame_index, PTS nguồn là authoritative cho sample.
4. Feedback: đánh dấu relevant/irrelevant, bật sử dụng feedback rồi tìm lại; giải thích Rocchio thay query vector, không fine-tune model. Reset session.
5. Kết hợp/A→B: OCR/ASR unavailable trên data thật; dùng fixture riêng để demo các kênh, banner fixture phải hiện. Temporal cần cùng video và gap>0 trong giới hạn ms.
6. DRES dry run: chọn evaluation/task_key, preview KIS, preview QA `007`, chỉ ra JSON ms và không tiền tố QA-. Submit dry run lưu ledger local, không gọi network. Mock task phải có nhãn local được khai báo riêng, không lấy rank1 làm bằng chứng đúng.
7. Đánh giá: chưa có labels thật thì trình bày schema/tool, không đưa số Recall bịa. Chạy pytest và lab để minh họa kiểm chứng toán học/contract.

## Câu hỏi thường được hỏi

**Vì sao L2 + inner product?** Khi norm ảnh/query=1, inner product bằng cosine. Không chuẩn hóa thì độ lớn vector tác động score; `app.index.normalize` kiểm tra zero/NaN.

**Vì sao RRF?** Cosine và BM25 khác thang; RRF dùng rank trong từng kênh, cộng w/(60+rank). Contributions giúp thấy ảnh hưởng từng nguồn, không là confidence.

**Chứng minh thời gian300frame25FPS?** Chỉ khi CFR đã xác nhận, index gốc0, 300×1000/25=12000ms. Với VFR cần PTS; ảnh đại diện thứ300 không mặc định là frame gốc300.

**Bộ kiểm thử chứng minh điều gì?** Fixture chứng minh invariant/index/payload; video thật chứng minh integration; chỉ labels thật mới chứng minh retrieval quality. CUDA/Linux/liveDRES chưa chạy không ghi pass.

**Hệ thống có phân tán không?** Không. Shard và batch liên hệ SPIMI/BSBI nhưng process local không là MapReduce cluster. PageRank lab chạy graph local, dataset không tự có hyperlink.

**Baseline kế thừa gì?** Ý tưởng image/text embedding và video search; code app/UI viết mới, lỗi audit có regression test. Repo baseline chưa rõ giấy phép, không vendor lại nguyên repo.
