# Backend và hợp đồng HTTP

Factory `app.main.create_app(settings=None)` chạy với `uvicorn app.main:create_app --factory`. Lifespan tạo Database, RetrievalService, DresService; import không nạp model. Một worker, bind loopback mặc định. CORS development chỉ cho localhost/127.0.0.1:5173. API contract chi tiết ở [API_CONTRACT.md](API_CONTRACT.md).

| Endpoint thật | Input/output quan trọng |
|---|---|
| GET `/api/health`, `/api/capabilities` | health độc lập weights; modes/reasons/index_version/fixture |
| POST `/api/search` | SearchRequest typed; visual_text/ocr/asr/hybrid/temporal, filter trước top-k |
| POST `/api/search/image` | multipart file ≤10MiB, top_k query param; guard contest server |
| POST `/api/search/example` | keyframe_id, top_k; guard contest server |
| GET `/api/videos/{uid}/neighbors` | timestamp_ms; tối đa 13 frame gần mốc |
| GET `/api/media/video/{uid}`, `/api/media/thumbnail/{id}` | safe resolve trong data root; video Range/206/416 |
| POST `/api/feedback`, GET/DELETE `/api/feedback/{session}` | upsert, khôi phục hoặc reset feedback |
| GET/POST `/api/candidates`, DELETE `/api/candidates/{id}` | lưu ID/note bền vững |
| GET `/api/data`, `/api/history` | SQL counts/jobs/queries/submissions thực tế |
| GET `/api/dres/evaluations` | evaluation explicit; không tự chọn đầu danh sách |
| POST `/api/dres/preview`, `/api/dres/submit` | cùng input, preview không network, submit là thao tác riêng |
| POST `/api/dres/mock/start` | nhãn local + start clock task |
| GET `/api/evaluation`, POST `/api/evaluation/labels` | report có provenance; labels validate interval/video |

Ví dụ `{"mode":"visual_text","query":"people outdoors","top_k":8,"start_ms":10000,"end_ms":20000}`. Kết quả gồm keyframe_id, video_uid, media_item_name, timestamp_ms, thumbnail_url, video_url, score và contributions. Không chứa absolute data path. Preview submission resolve media từ DB; frontend không được tự đổi tên media.

Errors dùng `{detail: ...}`: 400 nghiệp vụ/grammar, 403 contest/path/live guard, 404 ID/file thiếu, 409 duplicate ledger, 422 Pydantic validation, 503 model/adapter unavailable. Model inference trong threadpool HTTP; lock service giữ model load và Rocchio không đua nhau. Video stream không phải load toàn file vào RAM.

SQLite SCHEMA v1 nằm `app/db.py`, bảng migration ghi version. Foreign key trên mỗi connection, unique video/keyframe IDs, unique video/timestamp. Chưa có migration từ một dự án legacy vì workspace ban đầu không có DB. Khi thay schema cần thêm version thay vì xóa DB. Không lưu credentials trong DB.
