# Kiểm thử thực tế · 14/10/2026

Môi trường đã chạy: Windows 11, Python 3.12.10 venv riêng, Torch2.7.0 CPU, OpenCLIP2.32.0, PyAV16.0.1, Node24.11.0/npm11.6.1, Chrome có sẵn. Phiên bản Python đầy đủ ở requirements-lock.txt; frontend/package-lock.json khóa dependency graph. GPU được doctor phát hiện nhưng inference CUDA chưa chạy.

| Kiểm tra thực sự đã chạy | Kết quả |
|---|---|
| `python -m pytest -q` | **86 passed**, một warning deprecation của Starlette/AnyIO |
| `ruff check app tests scripts/smoke_real.py` | pass, scope E9/F63/F7/F82 cho syntax/undefined và lỗi Python nghiêm trọng |
| `python -m pip check` | No broken requirements found |
| frontend typecheck, ESLint, Vitest, production build | pass, **9 tests passed** |
| npm audit | 0 advisories theo report phiên này, không phải bảo đảm vĩnh viễn |
| real browser QA | **10 checks passed**, JavaScript errors=[] |
| OpenCLIP image/text + NumPy + API smoke thật | **2 video / 72 frame**, thật CPU float32 512 chiều |
| extract lại cùng cấu hình | resumed=true, không duplicate keyframe |
| embed lại cùng space/input/batch | reused_rows=72/72 |
| CLI inspect/doctor/lab/help | đã chạy, JSON report hợp lệ UTF-8 |
| PowerShell start/stop | đã chạy và kiểm tra local health/search; UTF-8 BOM cho Windows PowerShell |

Core Python có kiểm thử thời gian CFR hữu tỷ/VFR PyAV thực, frame index khác ordinal, thiếu metadata, row map/shard corruption, same-dimension encoder mismatch, filter top-k, FTS Boolean/phrase/BM25/TF-IDF, temporal boundaries, Rocchio bất biến, stale index, SQLite duration invariant, unsafe import timestamp, media ranges/traversal, DRES đồng thời/restart/timeout/redaction/payload/score. Hai interpreter độc lập kiểm tra fingerprint preprocessing ổn định: transform repr OpenCLIP có memory address đã được chuẩn hóa trước hash.

Browser QA trên process web riêng xác nhận query thị giác trả 24 kết quả thật, video decode/play và seek 2000ms→2s, image upload top_k12 được giữ, feedback/candidates qua reload, preview QA007 và dryrun submit riêng, navigation, viewport390px không overflow. Mock QA correct chỉ trên fixture riêng có ground truth khai báo tổng hợp. Không tạo nhãn relevance cho data thật, không gửi live DRES.

Evidence:

- [smoke-real.json](reports/smoke-real.json): source/model/hash/index, actual requests/results/raw latency.
- [ui-browser-report.json](reports/ui-browser-report.json): 10 browser checks và player evidence.
- [ui-real.png](reports/ui-real.png), [inspector](reports/ui-real-inspector.png), [DRES](reports/ui-real-dres.png), [mobile](reports/ui-mobile.png): screenshots đã nhìn trực tiếp.
- [resume-extract.json](reports/resume-extract.json), [resume-embedding.json](reports/resume-embedding.json): resume/cache đã chạy.
- [data_inventory.json](../data_inventory.json), [doctor](reports/doctor.json), [labs](reports/labs.json).
- [review-backend.md](reports/review-backend.md): báo cáo reproduction trước sửa; các phát hiện đã được xử lý và regression trong code cuối. Helper metric K0/grade coercion cũng đã chặn; giới hạn temporal anchor ghi EVALUATION.
- [dependency-audit.json](../frontend/qa/dependency-audit.json): audit frontend.

Latency smoke ba query có cold model load và warm query riêng; raw values trong report, không công bố chất lượng hoặc tốc độ toàn kho từ mẫu này. Media copy/thumbnail/vector đều ở data root local, không public lại dataset.

Chưa chạy: full indexing toàn 726 video; OCR/ASR extraction thực vì dependency/model/language chưa có; FAISS/Milvus runtime; CUDA/Linux; live DRES; benchmark relevance/ablation vì chưa labels thật. Whole DOCX render thiếu LibreOffice, nhưng XML và ảnh công thức đã đọc trực tiếp. Test fixture chỉ chứng minh contract, không thay thế các kiểm tra chưa có đầu vào.
