"""Hồi quy pipeline offline: timestamp gốc, ZIP an toàn, resume và invalidation."""
import json
import zipfile
from fractions import Fraction

import numpy as np
import pytest

from app.config import Settings
from app.db import Database
from app.pipeline import build_index, cfr_timestamp_ms, create_fixture, embed_dataset, extract_video, extract_zip, import_text, inspect_data, pts_timestamp_ms


def test_cfr_rational_and_vfr_pts_never_keyframe_ordinal():
    """Frame gốc 300@25fps là 12s; VFR dùng PTS, không dùng mean FPS."""
    assert cfr_timestamp_ms(300, 25, 1, confirmed_cfr=True) == 12000
    assert cfr_timestamp_ms(300, 30000, 1001, confirmed_cfr=True) == 10010
    assert pts_timestamp_ms(123456, Fraction(1, 1000), 120000) == 3456
    assert pts_timestamp_ms(4500, Fraction(1, 90000)) == 50
    for arguments in ((300, None, None, True), (300, 25, 1, False)):
        with pytest.raises(ValueError):
            cfr_timestamp_ms(arguments[0], arguments[1], arguments[2], confirmed_cfr=arguments[3])
    with pytest.raises(ValueError):
        pts_timestamp_ms(None, Fraction(1, 1000))


def test_zip_inventory_metadata_only_and_allowlist_limits(tmp_path):
    """ZIP dùng central directory; chỉ allowlist nhỏ được đọc, không overwrite."""
    archive = tmp_path / "batch.zip"
    with zipfile.ZipFile(archive, "w", allowZip64=True) as stream:
        stream.writestr("nested/video.mp4", b"video-fixture")
        stream.writestr("notes.txt", b"notes")
    report = inspect_data(archive)
    assert report["inspection"] == "zip64-central-directory"
    assert report["file_count"] == 2 and report["video_file_count"] == 1
    assert report["uncompressed_bytes"] == len(b"video-fixture") + 5
    with pytest.raises(ValueError, match="vượt"):
        extract_zip(archive, tmp_path / "out", ["nested/video.mp4"], 1)
    result = extract_zip(archive, tmp_path / "out", ["nested/video.mp4"])
    assert result["uncompressed_bytes"] == len(b"video-fixture")
    assert not (tmp_path / "out" / "notes.txt").exists()
    with pytest.raises(ValueError, match="ghi đè"):
        extract_zip(archive, tmp_path / "out", ["nested/video.mp4"])


@pytest.mark.parametrize("member", ["../escape.mp4", "..\\escape.mp4", "/abs.mp4", "C:/drive.mp4"])
def test_zip_slip_and_windows_backslash_rejected(tmp_path, member):
    """Kiểm tra cả slash Windows/Linux trước bất kỳ filesystem write."""
    archive = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(member, b"unsafe")
    with pytest.raises(ValueError, match="an toàn"):
        extract_zip(archive, tmp_path / "out", [member])
    assert not (tmp_path / "escape.mp4").exists()


@pytest.fixture
def fixture_dataset(tmp_path):
    """PyAV video tổng hợp có timestamp thật; encoder màu được ghi nhãn fixture."""
    settings = Settings(tmp_path, tmp_path / "metadata.sqlite3", tmp_path / "index")
    db = Database(settings.db_path)
    report = create_fixture(db, settings)
    return db, settings, report


def test_pts_extract_resume_and_full_resolution_mapping(fixture_dataset):
    """Ordinal keyframe #2 thực ra original frame #20, không frame #2."""
    db, settings, report = fixture_dataset
    path = settings.data_root / "fixture-input" / "FIXTURE_COLORS.mp4"
    rerun = extract_video(db, settings, path, source_batch="fixture", interval_ms=1000)
    assert rerun["resumed"] is True
    rows = db.rows("SELECT * FROM keyframes ORDER BY timestamp_ms")
    assert len(rows) == 6
    assert rows[2]["timestamp_ms"] == 2000
    assert rows[2]["original_frame_index"] == 20
    assert rows[2]["timestamp_source"] == "decoder_pts"
    assert (settings.data_root / "frames" / rows[2]["video_uid"] / f"{rows[2]['keyframe_id']}.jpg").is_file()
    second = embed_dataset(db, settings, fixture=True, batch_size=6)
    assert second["reused_rows"] == 6


def test_extraction_config_invalidates_embedding_cache(fixture_dataset):
    """Thay sampling không thể ghép index map cũ vào keyframe mới."""
    db, settings, report = fixture_dataset
    before = (settings.index_root / "CURRENT").read_text()
    path = settings.data_root / "fixture-input" / "FIXTURE_COLORS.mp4"
    new = extract_video(db, settings, path, source_batch="fixture", interval_ms=500, max_frames=4)
    assert new["frame_count"] == 4 and new["subset"] is True
    assert new["duration_ms"] == 6000
    with pytest.raises(ValueError, match="đã đổi"):
        build_index(db, settings)
    assert (settings.index_root / "CURRENT").read_text() == before
    embed_dataset(db, settings, fixture=True, batch_size=2)
    assert build_index(db, settings)["row_count"] == 4


def test_import_text_transaction_resume_and_duplicate_media_name(fixture_dataset, tmp_path):
    """Import lại không trùng, lỗi interval không ghi nửa batch; tên trùng chặn."""
    db, settings, report = fixture_dataset
    uid = report["video_uid"]
    path = tmp_path / "asr.json"
    path.write_text(json.dumps([{"video_uid": uid, "source": "asr", "start_ms": 500, "end_ms": 1000, "text": "Xin chào"}]), encoding="utf-8")
    import_text(db, path)
    count = db.one("SELECT count(*) AS n FROM text_segments")["n"]
    import_text(db, path)
    assert db.one("SELECT count(*) AS n FROM text_segments")["n"] == count
    path.write_text(json.dumps([{"video_uid": uid, "source": "ocr", "start_ms": 0, "end_ms": 7000, "text": "invalid"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        import_text(db, path)
    assert db.one("SELECT count(*) AS n FROM text_segments")["n"] == count
    first = db.one("SELECT * FROM videos WHERE video_uid=?", (uid,))
    first["video_uid"] = "duplicate-video"
    db.upsert_video(first)
    path.write_text(json.dumps([{"media_item_name": first["media_item_name"], "source": "asr", "start_ms": 0, "end_ms": 500, "text": "duplicate"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="trùng tên"):
        import_text(db, path)


def test_fixture_encoder_rejects_real_video(fixture_dataset):
    """Không dùng fixture encoder để âm thầm encode video HCMAI24 thật."""
    db, settings, report = fixture_dataset
    db.execute("UPDATE videos SET source_batch='batch1'")
    with pytest.raises(ValueError, match="Fixture encoder"):
        embed_dataset(db, settings, fixture=True)


def test_vfr_extraction_uses_decoded_pts_not_average_fps(tmp_path):
    """Video frame intervals biến đổi: original index/FPS không thể suy timestamp."""
    import av
    from PIL import Image
    input_path = tmp_path / "variable.mp4"
    with av.open(str(input_path), mode="w") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width, stream.height, stream.pix_fmt = 64, 64, "yuv420p"
        stream.codec_context.time_base = Fraction(1, 1000)
        # Không reorder B-frame trong fixture rất ngắn để muxer ghi duration PTS
        # đúng; phần cần kiểm tra là VFR timeline, không metadata input hỏng.
        stream.codec_context.max_b_frames = 0
        for timestamp in (0, 40, 120, 200, 520):
            frame = av.VideoFrame.from_image(Image.new("RGB", (64, 64), "red"))
            frame.pts, frame.time_base = timestamp, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    settings = Settings(tmp_path / "runtime", tmp_path / "runtime" / "metadata.sqlite3", tmp_path / "runtime" / "index")
    db = Database(settings.db_path)
    report = extract_video(db, settings, input_path, interval_ms=1)
    rows = db.rows("SELECT * FROM keyframes ORDER BY original_frame_index")
    assert [row["timestamp_ms"] for row in rows] == [0, 40, 120, 200, 520]
    assert [row["original_frame_index"] for row in rows] == [0, 1, 2, 3, 4]
    assert report["vfr_observed"] is True
