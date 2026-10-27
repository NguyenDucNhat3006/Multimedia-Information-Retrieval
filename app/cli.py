"""CLI offline Windows/Linux; extraction/embedding không chạy trong HTTP request.

Chạy ``python -m app.cli --help``. Mọi action data/model cần lệnh tường minh;
khởi động server không tự tải ZIP, weights, OCR hoặc ASR model.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import Settings
from .db import Database
from .pipeline import VIDEO_EXTENSIONS, atomic_json, build_index, create_fixture, doctor, embed_dataset, extract_video, extract_zip, import_text, inspect_data, run_asr, run_ocr


def _video_paths(inputs: list[str], limit: int) -> list[Path]:
    """Chọn danh sách ổn định trước decode; limit=0 là full explicit ingest."""
    videos = []
    for value in inputs:
        path = Path(value)
        if path.is_dir():
            videos.extend(sorted((item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS), key=lambda item: str(item)))
        elif path.is_file():
            videos.append(path)
        else:
            raise FileNotFoundError(f"Input không tồn tại: {path}")
    videos = list(dict.fromkeys(videos))
    if limit < 0:
        raise ValueError("limit phải >=0; 0 nghĩa toàn bộ input đã chọn.")
    if not videos:
        raise ValueError("Không tìm thấy video local trong input.")
    return videos[:limit] if limit else videos


def parser() -> argparse.ArgumentParser:
    """Khai báo interface CLI có thể khám phá và gọi từ tài liệu giảng dạy."""
    root = argparse.ArgumentParser(description="CS336 video retrieval: pipeline offline có timestamp PTS.")
    root.add_argument("--data-root", help="Thư mục runtime riêng, overrides CS336_DATA_ROOT.")
    commands = root.add_subparsers(dest="command", required=True)
    diagnostic = commands.add_parser("doctor", help="Đo CPU/RAM/VRAM/disk và dependency hiện tại.")
    diagnostic.add_argument("--output", help="JSON report bổ sung; mặc định data/doctor.json.")
    inspection = commands.add_parser("inspect-data", help="Metadata-only inventory thư mục hoặc ZIP64 central directory.")
    inspection.add_argument("paths", nargs="+", help="Một hoặc nhiều ZIP/thư mục local.")
    inspection.add_argument("--output", default="data_inventory.json")
    unzip = commands.add_parser("extract-zip", help="Extract allowlist nhỏ, chống traversal, không overwrite.")
    unzip.add_argument("path")
    unzip.add_argument("destination")
    unzip.add_argument("--member", action="append", required=True)
    unzip.add_argument("--max-bytes", type=int, default=2_000_000_000)
    for name in ("extract", "ingest"):
        extraction = commands.add_parser(name, help="PTS sample full frame + thumbnail" + (" → embed → publish index." if name == "ingest" else "."))
        extraction.add_argument("paths", nargs="+")
        extraction.add_argument("--batch", default="local", help="source_batch, giữ media_item_name của video.")
        extraction.add_argument("--interval-ms", type=int, default=1000)
        extraction.add_argument("--max-frames", type=int, help="Giới hạn frame/video cho smoke subset.")
        extraction.add_argument("--limit", type=int, default=3, help="Tối đa video từ input; mặc định 3; 0=toàn bộ.")
        if name == "ingest":
            extraction.add_argument("--batch-size", type=int, default=16)
            extraction.add_argument("--download-weights", action="store_true")
    embedding = commands.add_parser("embed", help="Encode cùng checkpoint/preprocess; resume chunk checksum.")
    embedding.add_argument("--batch-size", type=int, default=16)
    embedding.add_argument("--download-weights", action="store_true", help="Cho phép tải OpenCLIP weights vào data/model-cache.")
    indexing = commands.add_parser("index", help="Validate cache rồi atomic publish CURRENT.")
    indexing.add_argument("--shard-size", type=int, default=8192)
    text = commands.add_parser("import-text", help="OCR/ASR JSON/JSONL/CSV có timestamp ms.")
    text.add_argument("path")
    text.add_argument("--source", choices=("ocr", "asr"))
    ocr = commands.add_parser("ocr", help="Adapter Tesseract thật; không tự tải language data.")
    ocr.add_argument("--video-uid")
    ocr.add_argument("--language", default="vie+eng")
    asr = commands.add_parser("asr", help="Adapter faster-whisper thật, local-only mặc định.")
    asr.add_argument("video_uid")
    asr.add_argument("--model", default="small")
    asr.add_argument("--language", default="vi")
    asr.add_argument("--download-weights", action="store_true")
    commands.add_parser("fixture", help="Video màu synthetic + text có nhãn; riêng contract, không benchmark.")
    evaluation = commands.add_parser("evaluate", help="Đánh giá offline nhãn đã kiểm duyệt; không tự tạo relevance.")
    evaluation.add_argument("labels")
    evaluation.add_argument("--top-k", type=int, default=10)
    evaluation.add_argument("--output")
    commands.add_parser("lab", help="Boolean/TF-IDF/SPIMI, clustering/category và PageRank fixture có nhãn.")
    serving = commands.add_parser("serve", help="Chạy API một worker, không download/ingest side effect.")
    serving.add_argument("--host", default="127.0.0.1")
    serving.add_argument("--port", type=int, default=8000)
    mock = commands.add_parser("mock", help="Bắt đầu task local với ground truth do người dùng khai báo.")
    mock.add_argument("--task-key", required=True)
    mock.add_argument("--video-uid", required=True)
    mock.add_argument("--start-ms", type=int, required=True)
    mock.add_argument("--end-ms", type=int, required=True)
    mock.add_argument("--task-type", choices=("textual_kis", "video_kis", "qa"), default="textual_kis")
    mock.add_argument("--answer")
    return root


def main(argv: list[str] | None = None) -> int:
    """Execute lệnh, JSON output cho reproducibility; exit 1 khi pipeline thất bại."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    arguments = parser().parse_args(argv)
    if arguments.data_root:
        os.environ["CS336_DATA_ROOT"] = arguments.data_root
    settings = Settings.from_env()
    settings.ensure_directories()
    command = arguments.command
    try:
        if command == "doctor":
            result = doctor(settings)
            if arguments.output:
                atomic_json(Path(arguments.output), result)
        elif command == "inspect-data":
            reports = [inspect_data(path) for path in arguments.paths]
            conflicts = {}
            # So sánh batch từ filename inventory, không decode toàn kho.
            names = {}
            for report, value in zip(reports, arguments.paths):
                path = Path(value)
                if path.is_dir():
                    values = (item.name for item in path.rglob("*") if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS)
                else:
                    import zipfile
                    with zipfile.ZipFile(path) as archive:
                        values = [Path(item.filename).name for item in archive.infolist() if Path(item.filename).suffix.lower() in VIDEO_EXTENSIONS]
                for name in values:
                    names.setdefault(Path(name).stem, []).append(str(path))
            conflicts = {name: sources for name, sources in names.items() if len(sources) > 1}
            result = {"sources": reports, "cross_source_duplicate_media_names": conflicts} if len(reports) > 1 else reports[0]
            atomic_json(Path(arguments.output), result)
        elif command == "extract-zip":
            result = extract_zip(arguments.path, arguments.destination, arguments.member, arguments.max_bytes)
        elif command == "serve":
            import uvicorn
            uvicorn.run("app.main:create_app", factory=True, host=arguments.host, port=arguments.port, workers=1)
            return 0
        elif command == "lab":
            from .labs import run_labs
            result = run_labs()
        else:
            db = Database(settings.db_path)
            if command in ("extract", "ingest"):
                results = [extract_video(db, settings, path, arguments.batch, arguments.interval_ms, arguments.max_frames) for path in _video_paths(arguments.paths, arguments.limit)]
                result = {"videos": results}
                if command == "ingest":
                    result["embeddings"] = embed_dataset(db, settings, arguments.batch_size, arguments.download_weights)
                    result["index"] = build_index(db, settings)
            elif command == "embed":
                result = embed_dataset(db, settings, arguments.batch_size, arguments.download_weights)
            elif command == "index":
                result = build_index(db, settings, arguments.shard_size)
            elif command == "import-text":
                result = import_text(db, arguments.path, arguments.source)
            elif command == "ocr":
                result = run_ocr(db, settings, arguments.video_uid, arguments.language)
            elif command == "asr":
                result = run_asr(db, settings, arguments.video_uid, arguments.model, arguments.language, arguments.download_weights)
            elif command == "fixture":
                if db.one("SELECT 1 FROM videos WHERE source_batch!='fixture' LIMIT 1"):
                    raise ValueError("Fixture cần data root riêng; đang có video thật, dùng --data-root data-fixture.")
                result = create_fixture(db, settings)
            elif command == "evaluate":
                from .evaluation import evaluate_file
                result = evaluate_file(arguments.labels, settings, arguments.top_k, arguments.output)
            elif command == "mock":
                from .dres import DresService
                result = DresService(db, settings).start_mock({"task_key": arguments.task_key, "video_uid": arguments.video_uid, "start_ms": arguments.start_ms, "end_ms": arguments.end_ms, "task_type": arguments.task_type, "answer": arguments.answer})
            else:
                raise ValueError("Lệnh chưa được nhận diện.")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, ImportError) as error:
        print(json.dumps({"error": str(error), "command": command}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
