"""SQLite metadata/feedback/job; transaction đóng connection và migration không phá dữ liệu cũ."""

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import unicodedata
from .schemas import Video, Keyframe, TextSegment


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS videos(
video_uid TEXT PRIMARY KEY, media_item_name TEXT NOT NULL, source_batch TEXT NOT NULL,
relative_path TEXT NOT NULL, duration_ms INTEGER NOT NULL CHECK(duration_ms>0), fps_num INTEGER, fps_den INTEGER,
time_base TEXT, start_time REAL, codec TEXT, width INTEGER, height INTEGER, vfr INTEGER, fingerprint TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS video_media_name ON videos(media_item_name);
CREATE TABLE IF NOT EXISTS keyframes(
keyframe_id TEXT PRIMARY KEY, video_uid TEXT NOT NULL REFERENCES videos(video_uid), original_frame_index INTEGER,
timestamp_ms INTEGER NOT NULL CHECK(timestamp_ms>=0), thumbnail_path TEXT NOT NULL, timestamp_source TEXT NOT NULL,
encoder_id TEXT, UNIQUE(video_uid,timestamp_ms));
CREATE INDEX IF NOT EXISTS keyframe_timeline ON keyframes(video_uid,timestamp_ms);
CREATE TABLE IF NOT EXISTS text_segments(
segment_id TEXT PRIMARY KEY, video_uid TEXT NOT NULL REFERENCES videos(video_uid), start_ms INTEGER NOT NULL CHECK(start_ms>=0),
end_ms INTEGER NOT NULL CHECK(end_ms>=start_ms), source TEXT NOT NULL CHECK(source IN ('ocr','asr')),
text TEXT NOT NULL, normalized_text TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS segment_timeline ON text_segments(video_uid,source,start_ms,end_ms);
CREATE VIRTUAL TABLE IF NOT EXISTS text_fts USING fts5(segment_id UNINDEXED,source UNINDEXED,normalized_text,tokenize='unicode61 remove_diacritics 0');
CREATE TRIGGER IF NOT EXISTS segment_insert AFTER INSERT ON text_segments BEGIN
INSERT INTO text_fts(segment_id,source,normalized_text) VALUES(new.segment_id,new.source,new.normalized_text); END;
CREATE TRIGGER IF NOT EXISTS segment_delete AFTER DELETE ON text_segments BEGIN
DELETE FROM text_fts WHERE segment_id=old.segment_id; END;
CREATE TRIGGER IF NOT EXISTS segment_update AFTER UPDATE ON text_segments BEGIN
DELETE FROM text_fts WHERE segment_id=old.segment_id;
INSERT INTO text_fts(segment_id,source,normalized_text) VALUES(new.segment_id,new.source,new.normalized_text); END;
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,
progress INTEGER DEFAULT 0,total INTEGER DEFAULT 0,config_json TEXT DEFAULT '{}',error TEXT,
created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS query_history(query_id TEXT PRIMARY KEY,request_json TEXT NOT NULL,result_count INTEGER NOT NULL,
elapsed_ms REAL NOT NULL,index_version TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS feedback(session_id TEXT NOT NULL,keyframe_id TEXT NOT NULL REFERENCES keyframes(keyframe_id),
relevant INTEGER NOT NULL CHECK(relevant IN(0,1)),created_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(session_id,keyframe_id));
CREATE TABLE IF NOT EXISTS candidates(keyframe_id TEXT PRIMARY KEY REFERENCES keyframes(keyframe_id),note TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO schema_migrations(version) VALUES(1);
"""


class Database:
    """Mỗi request/process có connection riêng, WAL và unique constraint ngăn trùng khi resume."""

    def __init__(self, path: Path | str):
        """Khởi tạo migration schema v1 trong file local; không giữ connection giữa các thread."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        """Yield sqlite Row connection; commit khi thành công, rollback khi lỗi, luôn close."""
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rows(self, sql: str, params=()) -> list[dict]:
        """Trả các row thành dict; mọi giá trị động truyền qua parameters chống SQL injection."""
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        """Trả một row hoặc None để adapter chủ động xử lý missing metadata."""
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def execute(self, sql: str, params=()) -> int:
        """Thực thi một mutation nguyên tử; trả lastrowid cho bảng có rowid."""
        with self.connection() as conn:
            return conn.execute(sql, params).lastrowid

    def _upsert(self, table: str, key: str, data: dict):
        """Tên bảng/cột chỉ từ schema internal; không nhận chúng từ request người dùng."""
        columns = list(data)
        assignments = ",".join(f"{c}=excluded.{c}" for c in columns if c != key)
        self.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                     f"ON CONFLICT({key}) DO UPDATE SET {assignments}", tuple(data.values()))

    def upsert_video(self, data: dict):
        """Validate video gốc rồi insert/update theo video_uid, giữ nguyên media_item_name của BTC."""
        video = Video.model_validate(data).model_dump()
        # Kiểm tra và ghi trong cùng transaction để một import concurrent không vượt duration mới.
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            frame = conn.execute("SELECT MAX(timestamp_ms) AS last_ms FROM keyframes WHERE video_uid=?", (video["video_uid"],)).fetchone()
            text = conn.execute("SELECT MAX(end_ms) AS last_ms FROM text_segments WHERE video_uid=?", (video["video_uid"],)).fetchone()
            latest = max(frame["last_ms"] or 0, text["last_ms"] or 0)
            if latest > video["duration_ms"]:
                raise ValueError("Không thể giảm duration khi keyframe/transcript hiện có nằm ngoài timeline mới")
            columns = list(video)
            assignments = ",".join(f"{c}=excluded.{c}" for c in columns if c != "video_uid")
            conn.execute(f"INSERT INTO videos ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                         f"ON CONFLICT(video_uid) DO UPDATE SET {assignments}", tuple(video.values()))

    def upsert_keyframe(self, data: dict):
        """Từ chối timestamp vượt duration, không tự sửa thành FPS mặc định."""
        frame = Keyframe.model_validate(data)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            video = conn.execute("SELECT duration_ms FROM videos WHERE video_uid=?", (frame.video_uid,)).fetchone()
            if video is None or frame.timestamp_ms > video["duration_ms"]:
                raise ValueError("Video không tồn tại hoặc keyframe vượt duration_ms")
            row = frame.model_dump()
            columns = list(row)
            assignments = ",".join(f"{c}=excluded.{c}" for c in columns if c != "keyframe_id")
            conn.execute(f"INSERT INTO keyframes ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                         f"ON CONFLICT(keyframe_id) DO UPDATE SET {assignments}", tuple(row.values()))

    def import_text(self, data: dict | list[dict]):
        """Validate tất cả segment trước transaction; lỗi một row không để nửa batch vào index."""
        items = data if isinstance(data, list) else [data]
        validated = []
        for item in items:
            segment = TextSegment.model_validate(item)
            video = self.one("SELECT duration_ms FROM videos WHERE video_uid=?", (segment.video_uid,))
            if video is None or segment.end_ms > video["duration_ms"]:
                raise ValueError("TextSegment thiếu video hoặc vượt duration")
            segment.normalized_text = unicodedata.normalize("NFC", segment.text).casefold()
            json.loads(segment.metadata_json)
            validated.append(segment.model_dump())
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for row in validated:
                # Recheck dưới write lock: duration có thể đổi sau validation batch ngoài transaction.
                video = conn.execute("SELECT duration_ms FROM videos WHERE video_uid=?", (row["video_uid"],)).fetchone()
                if video is None or row["end_ms"] > video["duration_ms"]:
                    raise ValueError("Duration đã thay đổi; TextSegment nằm ngoài timeline")
                columns = list(row)
                assigns = ",".join(f"{c}=excluded.{c}" for c in columns if c != "segment_id")
                conn.execute(f"INSERT INTO text_segments ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                             f"ON CONFLICT(segment_id) DO UPDATE SET {assigns}", tuple(row.values()))
