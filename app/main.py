"""FastAPI điều phối retrieval, metadata và DRES; frontend chỉ biết ID/URL, không giữ secret."""

from contextlib import asynccontextmanager
from pathlib import Path
import json
import time
import uuid
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from . import __version__
from .config import Settings, ROOT
from .db import Database
from .media import media_response
from .schemas import SearchRequest, FeedbackRequest, CandidateRequest, SubmissionRequest, ExampleRequest, MockTaskRequest


def create_app(settings: Settings | None = None) -> FastAPI:
    """Factory Uvicorn --factory; chỉ mở DB/index trong lifespan, encoder nạp khi cần inference."""
    configuration = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        """Mỗi process có một service/model; chạy một worker để tránh nhân VRAM."""
        from .retrieval import RetrievalService
        from .dres import DresService
        configuration.ensure_directories()
        app.state.db = Database(configuration.db_path)
        app.state.retrieval = RetrievalService(app.state.db, configuration)
        app.state.dres = DresService(app.state.db, configuration)
        yield

    app = FastAPI(title="CS336 · Video Event Retrieval", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])

    def protect_image():
        """Luật Video KIS áp dụng tại server, gồm cả query-by-example."""
        if configuration.contest_mode and configuration.task_type.lower() == "video_kis":
            raise HTTPException(403, "Video KIS: hãy diễn tả bằng văn bản; truy vấn ảnh bị chặn theo profile 2024")

    def invoke(function, *args):
        """Chuyển lỗi adapter thành HTTP, giữ thông báo nghiệp vụ đã redact từ DRES."""
        try:
            return function(*args)
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from None
        except FileNotFoundError:
            raise HTTPException(503, "Thiếu file dữ liệu/model local; kiểm tra CLI và index trước khi tìm kiếm") from None
        except ValueError as exc:
            raise HTTPException(getattr(exc, "status_code", 400), str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(getattr(exc, "status_code", 503), str(exc)) from None

    def result_for(frame):
        """Ghép metadata thống nhất để neighbors/candidates sử dụng cùng giao diện result grid."""
        return {"keyframe_id": frame["keyframe_id"], "video_uid": frame["video_uid"],
                "media_item_name": frame["media_item_name"], "timestamp_ms": frame["timestamp_ms"],
                "thumbnail_url": f"/api/media/thumbnail/{frame['keyframe_id']}",
                "video_url": f"/api/media/video/{frame['video_uid']}", "score": 0, "contributions": {}}

    def remember(request, result, started):
        """Lưu query/result count, không lưu binary ảnh hoặc token DRES trong lịch sử."""
        result.setdefault("elapsed_ms", round((time.perf_counter() - started) * 1000, 3))
        result.setdefault("warnings", [])
        result.setdefault("index_version", None)
        query_id = uuid.uuid4().hex
        result["query_id"] = query_id
        app.state.db.execute("INSERT INTO query_history(query_id,request_json,result_count,elapsed_ms,index_version) VALUES(?,?,?,?,?)",
                             (query_id, json.dumps(request, ensure_ascii=False), len(result["results"]),
                              result["elapsed_ms"], result["index_version"]))
        return result

    @app.get("/api/health")
    def health():
        """Health không cần weights, dependency OCR/ASR hoặc kết nối DRES."""
        return {"status": "ok", "version": __version__}

    @app.get("/api/capabilities")
    def capabilities():
        """Trạng thái kênh dựa trên dữ liệu/index thực tế, giúp UI hiển thị unavailable rõ ràng."""
        result = app.state.retrieval.capabilities()
        result.update(contest_mode=configuration.contest_mode, task_type=configuration.task_type)
        if configuration.contest_mode and configuration.task_type == "video_kis":
            result["modes"]["image"] = False
            result.setdefault("reasons", {})["image"] = "Video KIS chặn đưa ảnh đề vào công cụ"
        return result

    @app.post("/api/search")
    def search(request: SearchRequest):
        """Validate query/filter rồi gọi encoder/index/fusion; thời gian response là ms."""
        started = time.perf_counter()
        payload = request.model_dump()
        return remember(payload, invoke(app.state.retrieval.search, payload), started)

    @app.post("/api/search/image")
    async def search_image(file: UploadFile = File(...), top_k: int = Query(24, ge=1, le=200)):
        """Ảnh upload tối đa 10MiB; bytes chỉ sống trong request, không được lưu vào history."""
        protect_image()
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(413, "Ảnh tối đa 10 MiB")
        # Inference sync chạy threadpool để không chặn event loop khi đang stream video.
        from starlette.concurrency import run_in_threadpool
        started = time.perf_counter()
        result = await run_in_threadpool(invoke, app.state.retrieval.search_image, content, top_k)
        return remember({"mode": "image", "top_k": top_k}, result, started)

    @app.post("/api/search/example")
    def search_example(request: ExampleRequest):
        """Dùng một keyframe làm ảnh mẫu, vẫn phải tuân luật contest phía server."""
        protect_image()
        started = time.perf_counter()
        result = invoke(app.state.retrieval.search_example, request.keyframe_id, request.top_k)
        return remember({"mode": "image", **request.model_dump()}, result, started)

    @app.get("/api/media/video/{video_uid}")
    def video(video_uid: str):
        """Phục vụ video đã đăng ký, HTTP Range dùng để seek; không nhận filesystem path từ client."""
        row = app.state.db.one("SELECT relative_path FROM videos WHERE video_uid=?", (video_uid,))
        if row is None:
            raise HTTPException(404, "Không tìm thấy video")
        return media_response(configuration.data_root, row["relative_path"])

    @app.get("/api/media/thumbnail/{keyframe_id}")
    def thumbnail(keyframe_id: str):
        """Thumbnail được resolve an toàn từ ID; không expose ổ đĩa của người dùng."""
        row = app.state.db.one("SELECT thumbnail_path FROM keyframes WHERE keyframe_id=?", (keyframe_id,))
        if row is None:
            raise HTTPException(404, "Không tìm thấy keyframe")
        return media_response(configuration.data_root, row["thumbnail_path"])

    @app.get("/api/videos/{video_uid}/neighbors")
    def neighbors(video_uid: str, timestamp_ms: int = Query(..., ge=0)):
        """Lấy các frame gần timestamp rồi sắp xếp timeline, không tải toàn video vào RAM."""
        rows = app.state.db.rows("SELECT k.*,v.media_item_name FROM keyframes k JOIN videos v USING(video_uid) "
                                "WHERE k.video_uid=? ORDER BY ABS(k.timestamp_ms-?) LIMIT 13", (video_uid, timestamp_ms))
        return {"results": [result_for(row) for row in sorted(rows, key=lambda r: r["timestamp_ms"])]}

    @app.get("/api/data")
    def data():
        """Dashboard chỉ hiển thị COUNT SQL và manifest thực, không con số minh họa."""
        db = app.state.db
        videos = db.rows("SELECT video_uid,media_item_name,source_batch,duration_ms,fps_num,fps_den,codec,width,height,vfr FROM videos ORDER BY media_item_name")
        counts = {"videos": len(videos), "keyframes": db.one("SELECT COUNT(*) AS n FROM keyframes")["n"]}
        for source in ("ocr", "asr"):
            counts[source] = db.one("SELECT COUNT(*) AS n FROM text_segments WHERE source=?", (source,))["n"]
        caps = app.state.retrieval.capabilities()
        jobs = db.rows("SELECT job_id,kind,status,progress,total,created_at,updated_at,error FROM jobs ORDER BY updated_at DESC LIMIT 100")
        for job in jobs:
            if job["error"]:
                job["error"] = "Job thất bại; xem thông báo CLI local để chẩn đoán input/dependency"
        return {"videos": videos, "counts": counts, "jobs": jobs,
                "index_version": caps.get("index_version"), "fixture": caps.get("fixture", False)}

    @app.post("/api/feedback")
    def feedback(request: FeedbackRequest):
        """Upsert theo session/keyframe; feedback không sửa vector của index."""
        if not app.state.db.one("SELECT 1 FROM keyframes WHERE keyframe_id=?", (request.keyframe_id,)):
            raise HTTPException(404, "Keyframe không tồn tại")
        app.state.db.execute("INSERT INTO feedback(session_id,keyframe_id,relevant) VALUES(?,?,?) "
                             "ON CONFLICT(session_id,keyframe_id) DO UPDATE SET relevant=excluded.relevant,created_at=CURRENT_TIMESTAMP",
                             (request.session_id, request.keyframe_id, int(request.relevant)))
        return {"status": "saved"}

    @app.get("/api/feedback/{session_id}")
    def get_feedback(session_id: str):
        """Khôi phục nhãn session sau reload; session ID không chứa thông tin đăng nhập."""
        rows = app.state.db.rows("SELECT keyframe_id,relevant FROM feedback WHERE session_id=?", (session_id,))
        return {"feedback": [{**row, "relevant": bool(row["relevant"])} for row in rows]}

    @app.delete("/api/feedback/{session_id}")
    def reset_feedback(session_id: str):
        """Reset feedback session, không xóa lịch sử query hay candidate."""
        app.state.db.execute("DELETE FROM feedback WHERE session_id=?", (session_id,))
        return {"status": "reset"}

    @app.get("/api/candidates")
    def candidates():
        """Trả candidate đã lưu với metadata result hiện tại."""
        rows = app.state.db.rows("SELECT k.*,v.media_item_name,c.note,c.created_at FROM candidates c JOIN keyframes k USING(keyframe_id) JOIN videos v USING(video_uid) ORDER BY c.created_at DESC")
        return {"candidates": [{**result_for(row), "note": row["note"], "created_at": row["created_at"]} for row in rows]}

    @app.post("/api/candidates")
    def save_candidate(request: CandidateRequest):
        """Lưu ứng viên theo ID, unique key ngăn nhấp hai lần tạo hai bản ghi."""
        if not app.state.db.one("SELECT 1 FROM keyframes WHERE keyframe_id=?", (request.keyframe_id,)):
            raise HTTPException(404, "Keyframe không tồn tại")
        app.state.db.execute("INSERT INTO candidates(keyframe_id,note) VALUES(?,?) ON CONFLICT(keyframe_id) DO UPDATE SET note=excluded.note",
                             (request.keyframe_id, request.note))
        return {"status": "saved"}

    @app.delete("/api/candidates/{keyframe_id}")
    def delete_candidate(keyframe_id: str):
        """Xóa duy nhất candidate được chỉ định, vẫn giữ feedback/history."""
        app.state.db.execute("DELETE FROM candidates WHERE keyframe_id=?", (keyframe_id,))
        return {"status": "deleted"}

    @app.get("/api/history")
    def history():
        """Lịch sử để tái hiện truy vấn và đối chiếu submission; không chứa secret."""
        queries = app.state.db.rows("SELECT * FROM query_history ORDER BY created_at DESC,rowid DESC LIMIT 100")
        for item in queries:
            item["request"] = json.loads(item.pop("request_json"))
        return {"queries": queries, "submissions": app.state.dres.history()}

    @app.get("/api/dres/evaluations")
    def evaluations():
        """Adapter trả evaluation mock/dry-run khi live chưa được bật có chủ ý."""
        return invoke(app.state.dres.evaluations)

    @app.post("/api/dres/preview")
    def preview(request: SubmissionRequest):
        """Chuẩn bị payload reviewable, preview không gửi mạng và không khóa ledger live."""
        return invoke(app.state.dres.preview, request.model_dump())

    @app.post("/api/dres/submit")
    def submit(request: SubmissionRequest):
        """Submit duy nhất khi client bấm nút riêng; reservation server ngăn double-click/đa tab."""
        return invoke(app.state.dres.submit, request.model_dump())

    @app.post("/api/dres/mock/start")
    def start_mock(request: MockTaskRequest):
        """Bắt đầu clock local bằng ground truth người dùng gán, không gọi server cuộc thi."""
        return invoke(app.state.dres.start_mock, request.model_dump())

    @app.get("/api/evaluation")
    def evaluation():
        """Liệt kê report đã chạy; khi chưa có nhãn không tạo số đo retrieval giả."""
        from .evaluation import LABEL_SCHEMA
        report_root = configuration.data_root / "evaluation"
        reports = []
        for path in sorted(report_root.glob("report*.json")):
            try:
                reports.append(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue
        labels = configuration.data_root / "labels.json"
        return {"reports": reports, "label_schema": LABEL_SCHEMA, "ground_truth_available": labels.is_file()}

    @app.post("/api/evaluation/labels")
    def labels(payload: dict):
        """Lưu bộ nhãn đã kiểm duyệt local; validator chặn interval/video/query thiếu."""
        from .evaluation import save_labels
        return invoke(save_labels, payload, configuration.data_root / "labels.json", app.state.db)

    # StaticFiles mount cuối cùng để /api luôn được resolve bởi API router.
    dist = ROOT / "frontend" / "dist"
    if (dist / "index.html").is_file():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            """Trang React điều hướng local; mọi API thiếu trả 404 thay vì HTML."""
            if path.startswith("api/"):
                raise HTTPException(404, "API không tồn tại")
            return FileResponse(dist / "index.html")

    return app
