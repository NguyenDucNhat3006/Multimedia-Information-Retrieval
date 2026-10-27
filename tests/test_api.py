"""Kiểm tra contract dùng fixture được ghi nhãn; không gọi server thi hoặc tải model."""

from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.db import Database
from app.main import create_app


@pytest.fixture
def configuration(tmp_path):
    """Metadata tối thiểu kiểm thử range/validation; bytes fixture không phải video semantic."""
    settings = Settings(data_root=tmp_path, db_path=tmp_path / "test.sqlite", index_root=tmp_path / "index")
    db = Database(settings.db_path)
    (tmp_path / "video.mp4").write_bytes(b"0123456789")
    (tmp_path / "thumb.jpg").write_bytes(b"image-fixture")
    db.upsert_video({"video_uid": "v1", "media_item_name": "VIDEO_1", "source_batch": "fixture", "relative_path": "video.mp4", "duration_ms": 20000, "fingerprint": "test"})
    for i in range(3):
        db.upsert_keyframe({"keyframe_id": f"k{i}", "video_uid": "v1", "timestamp_ms": i * 1000, "thumbnail_path": "thumb.jpg", "timestamp_source": "labelled_fixture"})
    db.import_text({"segment_id": "t1", "video_uid": "v1", "start_ms": 1000, "end_ms": 2000, "source": "ocr", "text": "xe đỏ"})
    return settings


def test_range_suffix_unsatisfiable_and_traversal(configuration):
    """Ngăn lỗi player không seek được hoặc byte Range vượt file; không mở path ngoài data root."""
    with TestClient(create_app(configuration)) as client:
        url = "/api/media/video/v1"
        partial = client.get(url, headers={"Range": "bytes=2-4"})
        assert partial.status_code == 206 and partial.content == b"234"
        assert client.get(url, headers={"Range": "bytes=-3"}).content == b"789"
        assert client.get(url, headers={"Range": "bytes=999-"}).status_code == 416
        db = Database(configuration.db_path)
        db.execute("UPDATE videos SET relative_path='../secret' WHERE video_uid='v1'")
        assert client.get(url).status_code == 403


def test_feedback_candidate_and_query_history(configuration):
    """API dùng DB thật, feedback/candidates idempotent và OCR có mapping thời gian."""
    with TestClient(create_app(configuration)) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        result = client.post("/api/search", json={"mode": "ocr", "query": "xe", "top_k": 10})
        assert result.status_code == 200, result.text
        assert result.json()["results"][0]["timestamp_ms"] == 1000
        assert len(client.get("/api/history").json()["queries"]) == 1
        for _ in range(2):
            assert client.post("/api/feedback", json={"session_id": "s", "keyframe_id": "k1", "relevant": True}).status_code == 200
            assert client.post("/api/candidates", json={"keyframe_id": "k1", "note": "xem lại"}).status_code == 200
        assert len(client.get("/api/candidates").json()["candidates"]) == 1
        assert client.get("/api/feedback/s").json()["feedback"] == [{"keyframe_id": "k1", "relevant": True}]
        assert client.delete("/api/feedback/s").status_code == 200
        assert client.get("/api/data").json()["counts"]["ocr"] == 1


def test_contest_blocks_both_image_paths(configuration):
    """Ẩn nút UI chưa đủ: image upload và example đều phải bị server chặn trong Video KIS."""
    settings = replace(configuration, contest_mode=True, task_type="video_kis")
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/search/example", json={"keyframe_id": "k1"}).status_code == 403
        assert client.post("/api/search/image", files={"file": ("x.png", b"png", "image/png")}).status_code == 403
        assert not client.get("/api/capabilities").json()["modes"]["image"]


def test_submit_preview_never_requires_network(configuration):
    """Preview exact payload, QA 007 không mất số đầu; mọi token thuộc server."""
    with TestClient(create_app(configuration)) as client:
        payload = {"keyframe_id": "k1", "task_type": "QA", "answer": "007", "evaluation_id": "local-mock", "task_key": "round1", "mode": "dry_run"}
        result = client.post("/api/dres/preview", json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["payload"] == {"answerSets": [{"answers": [{"text": "007-VIDEO_1-1000"}]}]}
        assert client.post("/api/dres/submit", json=payload).json()["status"] == "dry_run"


def test_invalid_duration_and_labels(configuration):
    """Không tự sửa metadata âm hoặc labels ngoài duration, giữ benchmark chỉ từ input hợp lệ."""
    db = Database(configuration.db_path)
    with pytest.raises(ValueError):
        db.upsert_keyframe({"keyframe_id": "bad", "video_uid": "v1", "timestamp_ms": 21000, "thumbnail_path": "thumb.jpg", "timestamp_source": "pts"})
    with TestClient(create_app(configuration)) as client:
        assert client.post("/api/search", json={"query": "q", "start_ms": 20, "end_ms": 10}).status_code == 422
        label = {"provenance": "human_reviewed", "split": "test", "queries": [{"query_id": "q1", "query": "q", "events": [{"event_id": "e1", "video_uid": "v1", "start_ms": 0, "end_ms": 21000, "grade": 1}]}]}
        assert client.post("/api/evaluation/labels", json=label).status_code == 400


@pytest.mark.parametrize("timestamp", [True, 1.0, "1000"])
def test_submission_time_requires_integer_ms(configuration, timestamp):
    """Ngăn JSON bool/float/string bị ép kiểu âm thầm thành ms trước chuẩn bị submit."""
    with TestClient(create_app(configuration)) as client:
        payload = {"keyframe_id": "k1", "timestamp_ms": timestamp, "evaluation_id": "local-mock", "task_key": "r1"}
        assert client.post("/api/dres/preview", json=payload).status_code == 422


def test_jobs_do_not_expose_input_path_and_labels_validate_mode(configuration):
    """Job exception có path local chỉ được đọc tại CLI; labels lỗi mode/B không được publish."""
    db = Database(configuration.db_path)
    db.execute("INSERT INTO jobs(job_id,kind,status,error,config_json) VALUES(?,?,?,?,?)",
               ("failed", "extract", "failed", "E:/private/video.mp4", '{"input":"E:/private/video.mp4"}'))
    with TestClient(create_app(configuration)) as client:
        data = client.get("/api/data")
        assert "E:/private" not in data.text and "config_json" not in data.text
        label = {"provenance": "human_reviewed", "split": "test", "queries": [{"query_id": "q", "query": "x", "mode": "temporal", "events": [{"event_id": "e", "video_uid": "v1", "start_ms": 0, "end_ms": 100, "grade": 1}]}]}
        assert client.post("/api/evaluation/labels", json=label).status_code == 400


def test_video_duration_cannot_shrink_below_children(configuration):
    """Một import video update không được để keyframe9000ms bên ngoài duration1000ms."""
    db = Database(configuration.db_path)
    video = db.one("SELECT * FROM videos WHERE video_uid='v1'")
    video["duration_ms"] = 500
    with pytest.raises(ValueError, match="duration"):
        db.upsert_video(video)
    assert db.one("SELECT duration_ms FROM videos WHERE video_uid='v1'")["duration_ms"] == 20000


def test_core_starts_during_incomplete_frontend_build(configuration, monkeypatch, tmp_path):
    """Vite có thể xóa assets giữa build; core health phải khởi động dù chỉ có dist folder."""
    import app.main
    root = tmp_path / "partial"
    (root / "frontend" / "dist").mkdir(parents=True)
    monkeypatch.setattr(app.main, "ROOT", root)
    with TestClient(create_app(configuration)) as client:
        assert client.get("/api/health").status_code == 200


@pytest.mark.parametrize("timestamp", [1.5, True, "1.5"])
def test_import_does_not_truncate_non_integer_timestamps(configuration, timestamp, tmp_path):
    """JSON/csv transcript sai đơn vị phải lỗi thay vì int(1.5)=1 làm lệch video submission."""
    import json
    from app.pipeline import import_text
    path = tmp_path / "văn bản có dấu.json"
    path.write_text(json.dumps([{"video_uid": "v1", "source": "asr", "start_ms": timestamp, "end_ms": 2000, "text": "x"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="integer"):
        import_text(Database(configuration.db_path), path)
