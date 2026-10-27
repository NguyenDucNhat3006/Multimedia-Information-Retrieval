"""Pipeline offline có job/checkpoint: inventory, PTS sampling, embed và index.

Chỉ xử lý input local được chọn, không tự tải dataset. Thời gian toàn bộ API và
SQLite là integer milliseconds trên timeline video gốc bắt đầu tại 0.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path, PurePosixPath

import numpy as np
from PIL import Image, ImageDraw

from .encoders import FixtureEncoder, OpenClipEncoder
from .index import publish_index, sha256_file
from .text_search import normalize_text


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".ts"}
PIPELINE_VERSION = "pts-shards-v1"


def _digest(value) -> str:
    """Identity cấu hình qua JSON canonical, giữ Unicode độc lập hệ điều hành."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    """Ghi checkpoint sau flush; interruption không để JSON bị cắt đôi."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def source_fingerprint(path: Path) -> str:
    """Sampled fingerprint size/mtime/đầu/cuối; không tuyên bố là full SHA256.

    Chỉ đọc tối đa 2 MiB/video để inventory/resume không băm cả 116 GB input.
    Checksum shard/weights vẫn là SHA256 toàn bộ file, kiểm tra khi nạp.
    """
    info = path.stat()
    digest = hashlib.sha256(f"{info.st_size}:{info.st_mtime_ns}".encode())
    with path.open("rb") as stream:
        digest.update(stream.read(1024 * 1024))
        stream.seek(max(0, info.st_size - 1024 * 1024))
        digest.update(stream.read(1024 * 1024))
    return "sampled-sha256:" + digest.hexdigest()


def inspect_data(path: Path | str, report_path: Path | str | None = None) -> dict:
    """Đọc ZIP64 central directory hoặc stat cây thư mục, không decode video.

    Returns: số file, extension, compressed/uncompressed bytes, top paths,
    filename conflict và các giá trị còn unknown. report_path là JSON tùy chọn.
    """
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input không tồn tại: {path}")
    entries = []
    archive = path.is_file() and zipfile.is_zipfile(path)
    if archive:
        with zipfile.ZipFile(path, "r", allowZip64=True) as stream:
            for entry in stream.infolist():
                if not entry.is_dir():
                    entries.append((entry.filename, entry.file_size, entry.compress_size))
    elif path.is_dir():
        for directory, _, names in os.walk(path):
            for name in names:
                file_path = Path(directory) / name
                if file_path.is_file() and not file_path.is_symlink():
                    size = file_path.stat().st_size
                    entries.append((file_path.relative_to(path).as_posix(), size, size))
    else:
        size = path.stat().st_size
        entries.append((path.name, size, size))
    extensions = Counter(PurePosixPath(name).suffix.lower() or "(none)" for name, _, _ in entries)
    top_paths = Counter(PurePosixPath(name).parts[0] if len(PurePosixPath(name).parts) > 1 else "(root)" for name, _, _ in entries)
    media_names = defaultdict(list)
    for name, _, _ in entries:
        if PurePosixPath(name).suffix.lower() in VIDEO_EXTENSIONS:
            media_names[PurePosixPath(name).stem].append(name)
    report = {"source": str(path), "inspection": "zip64-central-directory" if archive else "filesystem-stat", "archive_bytes": path.stat().st_size if archive else None, "file_count": len(entries), "video_file_count": sum(count for extension, count in extensions.items() if extension in VIDEO_EXTENSIONS), "compressed_bytes": sum(entry[2] for entry in entries), "uncompressed_bytes": sum(entry[1] for entry in entries), "extensions": dict(extensions), "top_level_paths": dict(top_paths), "examples": [{"path": name, "bytes": size, "compressed_bytes": compressed} for name, size, compressed in entries[:15]], "smallest_videos": [{"path": name, "bytes": size} for name, size, _ in sorted(entries, key=lambda entry: entry[1]) if PurePosixPath(name).suffix.lower() in VIDEO_EXTENSIONS][:10], "duplicate_media_names": {name: paths for name, paths in media_names.items() if len(paths) > 1}, "unknown": ["codec/fps/duration/VFR chưa decode hoặc probe", "tính tương thích encoder của vector có sẵn", "ground truth chưa kiểm duyệt"]}
    if report_path:
        atomic_json(Path(report_path), report)
    return report


def extract_zip(path: Path | str, destination: Path | str, allowlist: list[str], max_bytes: int = 2_000_000_000) -> dict:
    """Extract allowlist tường minh, chống Zip Slip/symlink và giới hạn byte.

    Không ghi đè file đã có, không ghi vào archive/input. CRC được zipfile kiểm
    tra khi đọc hết. Partial file bị xóa nếu extraction thất bại.
    """
    path, destination = Path(path).resolve(), Path(destination).resolve()
    if not allowlist or max_bytes <= 0:
        raise ValueError("Cần allowlist không rỗng và max_bytes dương.")
    extracted = []
    with zipfile.ZipFile(path, allowZip64=True) as archive:
        members = {entry.filename: entry for entry in archive.infolist()}
        selections = []
        for name in dict.fromkeys(allowlist):
            requested_parts = PurePosixPath(name.replace("\\", "/"))
            if requested_parts.is_absolute() or ".." in requested_parts.parts or any(":" in part for part in requested_parts.parts):
                raise ValueError(f"ZIP member không an toàn: {name}")
            if name not in members:
                raise ValueError(f"ZIP không có member: {name}")
            entry = members[name]
            normalized = name.replace("\\", "/")
            parts = PurePosixPath(normalized)
            if entry.is_dir() or parts.is_absolute() or ".." in parts.parts or any(":" in part for part in parts.parts) or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"ZIP member không an toàn: {name}")
            target = (destination / Path(*parts.parts)).resolve()
            if not target.is_relative_to(destination) or target == path or target.exists():
                raise ValueError(f"Không ghi đè hoặc thoát destination: {name}")
            selections.append((entry, target))
        total = sum(entry.file_size for entry, _ in selections)
        if total > max_bytes:
            raise ValueError(f"Allowlist cần {total} bytes, vượt max_bytes={max_bytes}.")
        if total > shutil.disk_usage(destination.parent if destination.parent.exists() else Path.cwd()).free:
            raise ValueError("Không đủ dung lượng trống để extract allowlist.")
        written = 0
        for entry, target in selections:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".extracting-" + uuid.uuid4().hex)
            try:
                with archive.open(entry) as source, temporary.open("xb") as output:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        written += len(block)
                        if written > max_bytes:
                            raise ValueError("ZIP vượt byte limit trong lúc giải nén.")
                        output.write(block)
                if temporary.stat().st_size != entry.file_size:
                    raise ValueError("ZIP member size không khớp central directory.")
                # Hard link bảo đảm không ghi đè nếu một process khác tạo target.
                os.link(temporary, target)
                temporary.unlink()
                extracted.append(str(target))
            finally:
                if temporary.exists():
                    temporary.unlink()
    return {"extracted": extracted, "uncompressed_bytes": written}


def cfr_timestamp_ms(frame_index: int, fps_num: int | None, fps_den: int | None, *, confirmed_cfr: bool = False) -> int:
    """Fallback chỉ khi CFR đã xác nhận và original frame index bắt đầu từ 0."""
    if not confirmed_cfr or frame_index < 0 or not fps_num or not fps_den or fps_num <= 0 or fps_den <= 0:
        raise ValueError("Thiếu FPS hợp lệ/CFR xác nhận; không được mặc định 25 FPS.")
    return round(Fraction(frame_index * 1000 * fps_den, fps_num))


def pts_timestamp_ms(pts: int | None, time_base: Fraction, origin_pts: int = 0) -> int:
    """PTS hữu tỷ -> ms chính xác; dùng được cho VFR, từ chối mốc âm/thiếu."""
    if pts is None or not time_base or time_base <= 0:
        raise ValueError("Frame thiếu PTS/time_base; không suy timestamp từ FPS trung bình.")
    value = round((pts - origin_pts) * time_base * 1000)
    if value < 0:
        raise ValueError("PTS frame âm trên timeline video gốc.")
    return value


def probe_video(path: Path | str) -> dict:
    """Đọc stream metadata qua PyAV; VFR giữ unknown nếu chưa đo PTS deltas."""
    import av
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("Input không có video stream.")
        stream = container.streams.video[0]
        duration = float(stream.duration * stream.time_base) if stream.duration is not None else (container.duration / av.time_base if container.duration is not None else None)
        if duration is None or not np.isfinite(duration) or duration <= 0:
            raise ValueError("Không có duration hợp lệ trong video metadata.")
        rate = stream.average_rate
        return {"duration_ms": round(duration * 1000), "fps_num": rate.numerator if rate else None, "fps_den": rate.denominator if rate else None, "time_base": str(stream.time_base), "start_time": float(stream.start_time * stream.time_base) if stream.start_time is not None else None, "codec": stream.codec_context.name, "width": stream.width, "height": stream.height, "vfr": None}


@contextmanager
def pipeline_job(db, kind: str, config: dict):
    """Job ledger bền vững; failure được lưu trước khi exception truyền lên CLI."""
    identifier = uuid.uuid4().hex
    db.execute("INSERT INTO jobs(job_id,kind,status,config_json) VALUES(?,?,?,?)", (identifier, kind, "running", json.dumps(config, ensure_ascii=False)))
    try:
        yield identifier
    except BaseException as error:
        db.execute("UPDATE jobs SET status='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (str(error)[:1000], identifier))
        raise
    else:
        db.execute("UPDATE jobs SET status='completed',updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (identifier,))


def extract_video(db, settings, path: Path | str, source_batch: str = "local", interval_ms: int = 1000, max_frames: int | None = None) -> dict:
    """Decode PTS, lưu full ảnh encoder và thumbnail riêng; resume idempotent.

    max_frames giới hạn smoke subset, không thay duration video gốc. Video ngoài
    data_root được copy vào media root để API chỉ phục vụ đường dẫn an toàn.
    """
    import av
    path = Path(path).resolve()
    if not path.is_file() or interval_ms <= 0 or (max_frames is not None and max_frames <= 0):
        raise ValueError("Cần file video, interval_ms và max_frames hợp lệ.")
    settings.ensure_directories()
    fingerprint = source_fingerprint(path)
    uid = "v_" + _digest({"batch": source_batch, "source": str(path)})[:24]
    config = {"pipeline_version": PIPELINE_VERSION, "fingerprint": fingerprint, "interval_ms": interval_ms, "max_frames": max_frames}
    config_hash = _digest(config)
    checkpoint = settings.data_root / "checkpoints" / f"extract-{uid}.json"
    if checkpoint.exists():
        prior = json.loads(checkpoint.read_text(encoding="utf-8"))
        rows = db.rows("SELECT keyframe_id,thumbnail_path,timestamp_ms FROM keyframes WHERE video_uid=?", (uid,))
        if prior.get("config_hash") == config_hash and len(rows) == prior.get("frame_count") and rows and all((settings.data_root / row["thumbnail_path"]).exists() and frame_image_path(settings, row).exists() for row in rows):
            return dict(prior, resumed=True)
    with pipeline_job(db, "extract", dict(config, video_uid=uid)) as job_id:
        metadata = probe_video(path)
        if path.is_relative_to(settings.data_root):
            local_path = path
        else:
            local_path = settings.data_root / "media" / uid / path.name
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if not local_path.exists() or source_fingerprint(local_path) != fingerprint:
                temporary = local_path.with_suffix(local_path.suffix + ".copying")
                shutil.copy2(path, temporary)
                os.replace(temporary, local_path)
        video = dict(metadata, video_uid=uid, media_item_name=path.stem, source_batch=source_batch, relative_path=local_path.relative_to(settings.data_root).as_posix(), fingerprint=fingerprint)
        frames = []
        next_sample, previous_pts, origin_pts = 0, None, None
        deltas = Counter()
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            origin_pts = stream.start_time
            for frame_index, frame in enumerate(container.decode(stream)):
                if frame.pts is None:
                    raise ValueError("Video có frame thiếu PTS; extraction dừng thay vì đoán FPS.")
                if origin_pts is None:
                    origin_pts = frame.pts
                timestamp = pts_timestamp_ms(frame.pts, frame.time_base or stream.time_base, origin_pts)
                if previous_pts is not None and frame.pts > previous_pts:
                    deltas[frame.pts - previous_pts] += 1
                previous_pts = frame.pts
                if timestamp < next_sample:
                    continue
                if timestamp > video["duration_ms"]:
                    raise ValueError("PTS vượt duration metadata; cần xác minh timeline input.")
                identifier = "kf_" + _digest({"video": uid, "timestamp": timestamp, "config": config_hash})[:28]
                full_path = settings.data_root / "frames" / uid / f"{identifier}.jpg"
                thumbnail_path = settings.data_root / "thumbnails" / uid / f"{identifier}.jpg"
                full_path.parent.mkdir(parents=True, exist_ok=True)
                thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
                image = frame.to_image().convert("RGB")
                image.save(full_path, quality=95)
                image.thumbnail((384, 216))
                image.save(thumbnail_path, quality=88)
                frames.append({"keyframe_id": identifier, "video_uid": uid, "original_frame_index": frame_index, "timestamp_ms": timestamp, "thumbnail_path": thumbnail_path.relative_to(settings.data_root).as_posix(), "timestamp_source": "decoder_pts", "encoder_id": None})
                next_sample = (timestamp // interval_ms + 1) * interval_ms
                db.execute("UPDATE jobs SET progress=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (len(frames), job_id))
                if max_frames and len(frames) >= max_frames:
                    break
        if not frames:
            raise ValueError("Video không decode được keyframe nào.")
        video["vfr"] = len(deltas) > 1 if deltas else None
        db.upsert_video(video)
        # Invalidation dữ liệu derived và feedback tham chiếu xảy ra cùng transaction.
        with db.connection() as connection:
            connection.execute("DELETE FROM feedback WHERE keyframe_id IN (SELECT keyframe_id FROM keyframes WHERE video_uid=?)", (uid,))
            connection.execute("DELETE FROM candidates WHERE keyframe_id IN (SELECT keyframe_id FROM keyframes WHERE video_uid=?)", (uid,))
            connection.execute("DELETE FROM keyframes WHERE video_uid=?", (uid,))
            for frame in frames:
                columns = list(frame)
                connection.execute("INSERT INTO keyframes(" + ",".join(columns) + ") VALUES(" + ",".join("?" for _ in columns) + ")", tuple(frame.values()))
        result = {"video_uid": uid, "media_item_name": path.stem, "frame_count": len(frames), "config_hash": config_hash, "sampling": config, "last_timestamp_ms": frames[-1]["timestamp_ms"], "duration_ms": video["duration_ms"], "subset": bool(max_frames), "vfr_observed": video["vfr"], "resumed": False}
        atomic_json(checkpoint, result)
        return result


def frame_image_path(settings, row: dict) -> Path:
    """Full-resolution frame mặc định; import cũ có thể chỉ có thumbnail."""
    full_path = settings.data_root / "frames" / row["video_uid"] / f"{row['keyframe_id']}.jpg" if row.get("video_uid") else None
    if full_path is not None and full_path.exists():
        return full_path
    # Resume rows thiếu uid lấy UID từ cấu trúc thumbnail nội bộ đã kiểm soát.
    thumbnail = settings.data_root / row["thumbnail_path"]
    inferred = settings.data_root / "frames" / thumbnail.parent.name / thumbnail.name
    return inferred if inferred.exists() else thumbnail


def dataset_fingerprints(db) -> tuple[str, str]:
    """Fingerprint dữ liệu và mapping hiện tại để từ chối embedding cache cũ."""
    videos = db.rows("SELECT video_uid,fingerprint FROM videos ORDER BY video_uid")
    frames = db.rows("SELECT keyframe_id,video_uid,timestamp_ms,thumbnail_path FROM keyframes ORDER BY keyframe_id")
    return _digest(videos), _digest(frames)


def embed_dataset(db, settings, batch_size: int = 16, allow_download: bool = False, fixture: bool = False) -> dict:
    """Encode streaming batches; cache có checksum/ID/config và giảm batch OOM.

    Fixture phải được bật tường minh. CLI --download-weights là nơi duy nhất cho
    phép tải OpenCLIP weights. Input image là ảnh full, không phải thumbnail UI.
    """
    if batch_size <= 0:
        raise ValueError("batch_size phải dương.")
    encoder = FixtureEncoder() if fixture else OpenClipEncoder(settings, allow_download=allow_download)
    encoder.load()
    rows = db.rows("SELECT * FROM keyframes ORDER BY keyframe_id")
    if not rows:
        raise ValueError("Chưa extract keyframe.")
    if fixture and db.one("SELECT 1 FROM videos WHERE source_batch!='fixture' LIMIT 1"):
        raise ValueError("Fixture encoder chỉ được dùng cho fixture rõ ràng.")
    metadata = dict(encoder.metadata)
    directory = settings.data_root / "embeddings" / metadata["encoder_id"].replace(":", "_")
    directory.mkdir(parents=True, exist_ok=True)
    chunks, processed, reused = [], 0, 0
    started = time.perf_counter()
    with pipeline_job(db, "embed", {"encoder_id": metadata["encoder_id"], "batch_size": batch_size, "fixture": fixture}) as job_id:
        offset = 0
        while offset < len(rows):
            batch = rows[offset:offset + batch_size]
            identifiers = [row["keyframe_id"] for row in batch]
            paths = [frame_image_path(settings, row) for row in batch]
            configuration = {"encoder_id": metadata["encoder_id"], "ids": identifiers, "images": [source_fingerprint(path) for path in paths]}
            cache_key = _digest(configuration)
            vector_path, mapping_path = directory / f"{cache_key}.npy", directory / f"{cache_key}.json"
            if vector_path.exists() and mapping_path.exists():
                cache_record = json.loads(mapping_path.read_text(encoding="utf-8"))
                if cache_record.get("vectors_sha256") != sha256_file(vector_path):
                    raise ValueError("Embedding cache corrupt; xóa chunk hỏng rồi encode lại.")
                values = np.load(vector_path, mmap_mode="r", allow_pickle=False)
                if values.shape != (len(batch), metadata["dimension"]) or cache_record.get("ids") != identifiers:
                    raise ValueError("Embedding cache mapping/dimension không khớp.")
                reused += len(batch)
            else:
                images = []
                try:
                    for path in paths:
                        with Image.open(path) as image:
                            images.append(image.convert("RGB"))
                    try:
                        values = encoder.encode_images(images)
                    except RuntimeError as error:
                        if "out of memory" in str(error).lower() and batch_size > 1:
                            batch_size = max(1, batch_size // 2)
                            if not fixture:
                                import torch
                                if torch.cuda.is_available():
                                    torch.cuda.empty_cache()
                            continue
                        raise
                finally:
                    for image in images:
                        image.close()
                temporary = vector_path.with_suffix(".npy.tmp")
                with temporary.open("wb") as stream:
                    np.save(stream, values.astype(np.float32), allow_pickle=False)
                os.replace(temporary, vector_path)
                cache_record = dict(configuration, vectors_sha256=sha256_file(vector_path))
                atomic_json(mapping_path, cache_record)
            chunks.append({"vectors": str(vector_path.relative_to(settings.data_root)), "mapping": str(mapping_path.relative_to(settings.data_root)), "rows": len(batch), "vectors_sha256": cache_record["vectors_sha256"], "mapping_sha256": sha256_file(mapping_path)})
            with db.connection() as connection:
                connection.executemany("UPDATE keyframes SET encoder_id=? WHERE keyframe_id=?", [(metadata["encoder_id"], identifier) for identifier in identifiers])
                connection.execute("UPDATE jobs SET progress=?,total=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (processed + len(batch), len(rows), job_id))
            offset += len(batch)
            processed += len(batch)
        dataset, keyframes = dataset_fingerprints(db)
        record = dict(metadata, chunks=chunks, row_count=processed, dataset_fingerprint=dataset, keyframe_fingerprint=keyframes, elapsed_ms=(time.perf_counter() - started) * 1000, reused_rows=reused, schema_version=1, pipeline_version=PIPELINE_VERSION)
        atomic_json(settings.data_root / "embeddings" / "manifest.json", record)
    return record


def build_index(db, settings, shard_size: int = 8192) -> dict:
    """Kiểm tra cache/mapping/fingerprint rồi publish một index bất biến mới."""
    path = settings.data_root / "embeddings" / "manifest.json"
    if not path.exists():
        raise ValueError("Chưa có embedding manifest; chạy embed trước.")
    record = json.loads(path.read_text(encoding="utf-8"))
    dataset, keyframes = dataset_fingerprints(db)
    if record.get("dataset_fingerprint") != dataset or record.get("keyframe_fingerprint") != keyframes:
        raise ValueError("Dataset/keyframes đã đổi; phải embed lại, không dùng mapping cũ.")
    if not record.get("fixture") and (record.get("model_name") != settings.model_name or record.get("pretrained") != settings.pretrained):
        raise ValueError("Model config đã đổi; cần encode lại.")
    rows = db.rows("SELECT keyframe_id,encoder_id FROM keyframes ORDER BY keyframe_id")
    if any(row["encoder_id"] != record["encoder_id"] for row in rows):
        raise ValueError("Mixed encoder space trong keyframe metadata.")

    def batches():
        observed_ids = set()
        for chunk in record["chunks"]:
            vector_path = (settings.data_root / chunk["vectors"]).resolve()
            mapping_path = (settings.data_root / chunk["mapping"]).resolve()
            if not vector_path.is_relative_to(settings.data_root) or not mapping_path.is_relative_to(settings.data_root):
                raise ValueError("Embedding manifest path ngoài data root.")
            if sha256_file(vector_path) != chunk["vectors_sha256"]:
                raise ValueError("Embedding chunk checksum sai.")
            if sha256_file(mapping_path) != chunk.get("mapping_sha256"):
                raise ValueError("Embedding mapping checksum sai; không chấp nhận map thiếu provenance.")
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            if mapping["encoder_id"] != record["encoder_id"] or mapping["vectors_sha256"] != chunk["vectors_sha256"]:
                raise ValueError("Embedding mapping/encoder mismatch.")
            observed_ids.update(mapping["ids"])
            yield mapping["ids"], np.load(vector_path, mmap_mode="r", allow_pickle=False)
        if observed_ids != {row["keyframe_id"] for row in rows}:
            raise ValueError("Embedding mapping không bao phủ đúng tập keyframes hiện tại.")

    with pipeline_job(db, "index", {"encoder_id": record["encoder_id"], "shard_size": shard_size}):
        metadata = {key: record[key] for key in ("encoder_id", "dimension", "checkpoint_sha256", "preprocessing_hash", "fixture", "model_name", "pretrained")}
        return publish_index(settings.index_root, batches(), metadata, dataset_fingerprint=dataset, keyframe_fingerprint=keyframes, shard_size=shard_size)


def import_text(db, path: Path | str, source: str | None = None) -> dict:
    """Import JSON array/JSONL/CSV, resolve media name chỉ khi không mơ hồ.

    Mỗi row có video_uid (hoặc media_item_name), start_ms,end_ms,source,text.
    Batch validate xong mới commit; ID content-stable nên import lại không trùng.
    """
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            items = list(csv.DictReader(stream))
    elif path.suffix.lower() == ".jsonl":
        items = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    else:
        parsed = json.loads(path.read_text(encoding="utf-8-sig"))
        items = parsed if isinstance(parsed, list) else parsed.get("segments", [])
    normalized = []
    for item in items:
        video_uid = item.get("video_uid")
        if not video_uid:
            videos = db.rows("SELECT video_uid FROM videos WHERE media_item_name=?", (item.get("media_item_name"),))
            if len(videos) != 1:
                raise ValueError("media_item_name thiếu/không tồn tại/trùng tên; cần video_uid tường minh.")
            video_uid = videos[0]["video_uid"]
        channel = source or item.get("source")
        if channel not in ("ocr", "asr"):
            raise ValueError("source phải là ocr hoặc asr.")
        def integer_ms(value):
            """CSV có chuỗi số nguyên; JSON float/bool không được cắt phần thập phân thành ms."""
            if type(value) is int:
                return value
            if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
                return int(value)
            raise ValueError("Timestamp import phải là integer milliseconds, không phải float/bool")
        start, end = integer_ms(item["start_ms"]), integer_ms(item.get("end_ms", item["start_ms"]))
        row = {"video_uid": video_uid, "start_ms": start, "end_ms": end, "source": channel, "text": item["text"], "normalized_text": normalize_text(item["text"]), "metadata_json": json.dumps(item.get("metadata", {}), ensure_ascii=False)}
        row["segment_id"] = item.get("segment_id") or "seg_" + _digest(row)[:28]
        normalized.append(row)
    with pipeline_job(db, "import-text", {"source": source, "rows": len(normalized)}):
        db.import_text(normalized)
    return {"imported": len(normalized), "sources": dict(Counter(row["source"] for row in normalized))}


def run_ocr(db, settings, video_uid: str | None = None, language: str = "vie+eng") -> dict:
    """Adapter Tesseract thực trên full frame; giữ box/confidence/timestamp.

    Không tải language data. Thiếu binary/lang/dependency báo lỗi khả dụng rõ.
    """
    try:
        import pytesseract
    except ImportError as error:
        raise RuntimeError("OCR cần pytesseract và Tesseract binary đã cài.") from error
    available_languages = set(pytesseract.get_languages(config=""))
    missing = set(language.split("+")) - available_languages
    if missing:
        raise RuntimeError("Tesseract thiếu language data: " + ", ".join(sorted(missing)))
    frames = db.rows("SELECT * FROM keyframes" + (" WHERE video_uid=?" if video_uid else ""), (video_uid,) if video_uid else ())
    count = 0
    with pipeline_job(db, "ocr", {"video_uid": video_uid, "language": language}):
        for frame in frames:
            with Image.open(frame_image_path(settings, frame)) as image:
                data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
            boxes, words = [], []
            for index, word in enumerate(data["text"]):
                if word.strip() and float(data["conf"][index]) >= 0:
                    words.append(word.strip())
                    boxes.append({"text": word.strip(), "confidence": float(data["conf"][index]), "left": data["left"][index], "top": data["top"][index], "width": data["width"][index], "height": data["height"][index]})
            text = " ".join(words)
            if text:
                db.import_text({"segment_id": "ocr_" + frame["keyframe_id"], "video_uid": frame["video_uid"], "start_ms": frame["timestamp_ms"], "end_ms": frame["timestamp_ms"], "source": "ocr", "text": text, "metadata_json": json.dumps({"engine": "tesseract", "language": language, "boxes": boxes}, ensure_ascii=False)})
                count += 1
    return {"imported": count, "engine": "tesseract", "language": language}


def run_asr(db, settings, video_uid: str, model_name: str = "small", language: str = "vi", allow_download: bool = False) -> dict:
    """Adapter faster-whisper thực; local_files_only mặc định, segments theo ms."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError("ASR cần dependency tùy chọn faster-whisper.") from error
    video = db.one("SELECT * FROM videos WHERE video_uid=?", (video_uid,))
    if not video:
        raise ValueError("Không có video_uid cho ASR.")
    cache = settings.data_root / "model-cache" / "whisper"
    cache.mkdir(parents=True, exist_ok=True)
    with pipeline_job(db, "asr", {"video_uid": video_uid, "model_name": model_name, "language": language}):
        model = WhisperModel(model_name, device="cpu", compute_type="int8", download_root=str(cache), local_files_only=not allow_download)
        segments, information = model.transcribe(str(settings.data_root / video["relative_path"]), language=language or None, vad_filter=True)
        rows = []
        for segment in segments:
            start, end = round(segment.start * 1000), min(round(segment.end * 1000), video["duration_ms"])
            if start > end:
                raise ValueError("ASR segment lệch timeline video gốc.")
            rows.append({"segment_id": "asr_" + _digest([video_uid, model_name, start, end, segment.text])[:28], "video_uid": video_uid, "start_ms": start, "end_ms": end, "source": "asr", "text": segment.text.strip(), "metadata_json": json.dumps({"engine": "faster-whisper", "model": model_name, "language": information.language, "avg_logprob": segment.avg_logprob})})
        db.import_text(rows)
    return {"imported": len(rows), "engine": "faster-whisper", "language": information.language}


def create_fixture(db, settings) -> dict:
    """Tạo video màu + nhãn text tổng hợp; không được dùng làm benchmark thật."""
    import av
    settings.ensure_directories()
    source = settings.data_root / "fixture-input" / "FIXTURE_COLORS.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        with av.open(str(source), mode="w") as container:
            stream = container.add_stream("libx264", rate=10)
            stream.width, stream.height, stream.pix_fmt = 320, 180, "yuv420p"
            for frame_number in range(60):
                color, label = [("red", "RED - FIXTURE"), ("green", "GREEN - FIXTURE"), ("blue", "BLUE - FIXTURE")][frame_number // 20]
                image = Image.new("RGB", (320, 180), color)
                ImageDraw.Draw(image).text((12, 14), label, fill="white")
                frame = av.VideoFrame.from_image(image)
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
    extraction = extract_video(db, settings, source, source_batch="fixture", interval_ms=1000)
    uid = extraction["video_uid"]
    texts = [(0, 1999, "red đỏ fixture"), (2000, 3999, "green xanh lá fixture"), (4000, 5999, "blue xanh dương fixture")]
    db.import_text([{"segment_id": f"fixture_{channel}_{start}", "video_uid": uid, "start_ms": start, "end_ms": end, "source": channel, "text": text, "metadata_json": '{"fixture":true,"provenance":"declared synthetic colors"}'} for channel in ("ocr", "asr") for start, end, text in texts])
    embedding = embed_dataset(db, settings, fixture=True, batch_size=6)
    index = build_index(db, settings, shard_size=3)
    return {"fixture": True, "video_uid": uid, "extraction": extraction, "embedding_rows": embedding["row_count"], "index_version": index["version"], "warning": "Synthetic contract fixture, không phải HCMAI24 semantic benchmark."}


def doctor(settings) -> dict:
    """Đo môi trường hiện tại: Python/CPU/RAM/đĩa/GPU/dependency, không giả VRAM."""
    import importlib.util
    import importlib.metadata
    settings.ensure_directories()
    versions = {}
    for package in ("numpy", "Pillow", "av", "torch", "torchvision", "open_clip_torch", "fastapi", "pytesseract", "faster-whisper", "faiss-cpu"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    ram = None
    if importlib.util.find_spec("psutil"):
        import psutil
        ram = psutil.virtual_memory().total
    elif os.name == "nt":
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong), ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong), ("avail_extended", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            ram = status.total_phys
    gpu = {"available": False, "reason": "nvidia-smi không có hoặc chưa kiểm tra được"}
    try:
        output = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15, check=True)
        gpu = {"available": True, "nvidia_smi": output.stdout.strip()}
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    result = {"python": platform.python_version(), "python_executable": os.sys.executable, "os": platform.platform(), "logical_cpu_count": os.cpu_count(), "ram_bytes": ram, "data_drive": str(settings.data_root.anchor), "disk_free_bytes": shutil.disk_usage(settings.data_root).free, "gpu": gpu, "device_config": settings.device, "packages": versions, "ffmpeg_binary": shutil.which("ffmpeg"), "ffprobe_binary": shutil.which("ffprobe"), "weights_local": OpenClipEncoder(settings).available}
    atomic_json(settings.data_root / "doctor.json", result)
    return result
