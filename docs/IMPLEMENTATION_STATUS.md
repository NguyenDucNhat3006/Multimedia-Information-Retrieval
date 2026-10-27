# Trạng thái triển khai và kiểm chứng

Tài liệu này tách phần đã có code, phần đã chạy trên môi trường hiện tại và phần còn cần đầu vào. Kết quả checks cuối cùng cùng đường dẫn report nằm trong `docs/VALIDATION.md`. Một adapter tồn tại không đồng nghĩa extraction/integration thực của adapter đó đã được kiểm tra.

## M0 — Đầu vào, audit và schema

Đã đọc bản scan đề cương 14 trang, OOXML của DOCX quy định AIC2024 và ảnh công thức. Baseline được audit tại SHA đã ghi trong `docs/BASELINE_AUDIT.md`; upstream DRES schema snapshot và hash được lưu để đối chiếu.

Doctor chạy trên Windows. Inventory metadata-only quan sát hai input local, mỗi nguồn 363 MP4, tổng 726 video; so sánh media stem chưa thấy trùng tên giữa hai nguồn. Schema Pydantic, SQLite migrations và API contract đã hiện thực, có tests. Đề cương là nội dung học phần, không được tự coi là rubric riêng của đồ án.

Chưa chạy whole-document DOCX renderer do môi trường thiếu LibreOffice; việc đọc XML và ảnh công thức được ghi rõ theo phương thức thực tế. Inventory không decode toàn kho, nên codec/FPS/duration của những video chưa probe còn unknown.

## M1 — Luồng visual tối thiểu trên dữ liệu thật

Đã hiện thực PyAV sampling theo PTS, ảnh full và thumbnail riêng, copy video local vào media root an toàn, OpenCLIP float32 CPU, L2-normalized NumPy shards/mmap, manifest/checksum/row mapping và atomic `CURRENT`. API text search, React result grid và player seek có code cùng tests.

Smoke integration chọn 2 video thật với 72 keyframe; dimension model đo được 512. Đây là sample các đoạn đầu, không phải index toàn bộ 726 video hoặc toàn thời lượng hai video. Video gốc vẫn đầy đủ. Resume extraction và embedding chunk đã thử; số liệu và response lưu trong `docs/reports/smoke-real.json`, report resume cùng inventory/doctor.

Browser QA kiểm tra luồng website với backend process độc lập; kết quả cuối cùng được ghi trong `docs/VALIDATION.md` và `docs/reports/ui-browser-report.json`. Cross-process encoder identity được kiểm tra riêng vì hash preprocessing không được phụ thuộc memory address của transform. Không coi TestClient cùng process là đủ thay cho phép kiểm tra này.

## M2 — Retrieval và tương tác

Đã hiện thực và kiểm thử contract: image upload/example, contest guard phía server, filter trước top-k, Unicode Boolean/phrase/NOT, TF-IDF lab, production FTS BM25, import text idempotent, interval anchor, weighted RRF/contributions, temporal đúng video/thứ tự/gap, Rocchio cùng space, reset feedback, candidates và query history. Visual/image/temporal trên subset thật có smoke report; semantic relevance chưa có benchmark nhãn thật.

OCR Tesseract và ASR faster-whisper có adapter thực, nhưng chưa có đầy đủ dependency/model/language data để extract trên media thật trong integration hiện tại. Capability OCR/ASR của dữ liệu thật vẫn unavailable. Text fixture có provenance tổng hợp, không được gọi là transcript/OCR trích từ HCMAI24.

Chưa có workflow import vector ngoài được xác minh provenance. Vector thiếu checkpoint/preprocessing/mapping evidence phải cách ly hoặc re-encode. FAISS CPU có adapter, chưa cài/kiểm tra runtime; Milvus profile chưa hiện thực và không phải điều kiện chạy bản nhẹ. Không có translator tự động, paid API hoặc fine-tuning trong baseline này.

## M3 — DRES

Đã hiện thực và kiểm thử profile `aic2024_v2`, exact KIS/QA milliseconds, ASCII digits giữ `007`, preview, dry run, mock với ground truth local/clock, SQLite ledger qua concurrent requests/restart, task-key scope và namespace isolation. Tests kiểm tra duplicate/double click, timeout thành unknown không auto retry, accepted/pending khác correct, HTTP error handling và secret redaction.

Live adapter login/evaluation/submit có code nhưng **live integration chưa chạy** vì chưa có server/schema/luật thi hiện tại cùng credentials được cung cấp. Automated tests không gọi server cuộc thi thật. Profile 2024 là tham chiếu theo DOCX, không chứng minh server lịch sử đang hoạt động hoặc được phép dùng cho lớp hiện tại.

## M4 — Đánh giá, lab và tài liệu

Đã có label schema/tool, event-level Precision/Recall/MRR/nDCG, AP/mAP@K với guard exhaustive judgments và report latency/provenance/index version. Lab Boolean/VSM, categorization, clustering và PageRank chạy trên fixture được ghi nhãn. Course mapping phân biệt core, lab và nội dung giải thích, không tuyên bố pipeline local là MapReduce phân tán.

Tutorial hướng dẫn toàn bộ code flow, setup/start/stop Windows và hướng dẫn Linux được viết theo module/CLI thực. Frontend typecheck/lint/component tests/build và browser checks có kết quả trong validation report. Windows CPU là môi trường đã chạy; Linux và CUDA inference chưa được thực thi trong phiên này.

**Offline relevance benchmark và ablation trên dữ liệu thật chưa có kết quả:** cần labels query/event do người kiểm duyệt. Không tự sinh Recall/MRR từ result ranking. Raw smoke latency đã lưu, nhưng số query/subset nhỏ không đủ để cam kết tốc độ toàn kho.

## Đầu vào cần cho bước tiếp theo

- Nhãn query/event đã kiểm duyệt, tách dev/test để chọn weights và đánh giá chất lượng thật.
- Nguồn OCR/ASR có timestamp, hoặc dependency/model/language data để chạy extraction trên media thật.
- Server, schema, luật thi hiện tại và backend credentials để thực hiện live DRES test có chủ đích.
- Data volume đủ disk/RAM theo inventory, cùng mapping chính thức nếu phát hiện media name trùng khi mở rộng nguồn.

Input gốc của người dùng được giữ nguyên. Không tự công khai dataset hoặc toàn bộ baseline code. Những phần chưa chạy được ghi theo module và evidence cần bổ sung; tests/fixture không được dùng để thay thế benchmark hoặc verdict thi thật.
