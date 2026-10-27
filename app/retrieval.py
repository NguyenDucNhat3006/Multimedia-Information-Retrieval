"""Application retrieval: visual, OCR/ASR, weighted RRF, temporal và Rocchio.

Backend gọi service đồng bộ trong worker thread. Index được nạp lười và cache
theo CURRENT, không import model khi khởi động API hoặc khi tìm text OCR/ASR.
"""
from __future__ import annotations

import io
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict
from threading import RLock

import numpy as np
from PIL import Image, UnidentifiedImageError

from .encoders import EncoderUnavailable, encoder_for_manifest
from .index import NumpyShardIndex, normalize
from .text_search import search_database


def weighted_rrf(channels: dict[str, list[dict]], weights: dict[str, float], constant: int = 60) -> list[dict]:
    """Fusion theo rank, tránh cộng cosine với BM25 khác đơn vị.

    Mỗi keyframe chỉ nhận một đóng góp/channel; score không là confidence.
    """
    fused: dict[str, dict] = {}
    for channel, results in channels.items():
        weight = float(weights.get(channel, 1))
        seen = set()
        for rank, result in enumerate(results, 1):
            identifier = result["keyframe_id"]
            if identifier in seen:
                continue
            seen.add(identifier)
            contribution = weight / (constant + rank)
            if identifier not in fused:
                fused[identifier] = dict(result, score=0.0, contributions={})
            fused[identifier]["score"] += contribution
            fused[identifier]["contributions"][channel] = {"rank": rank, "raw_score": result["score"], "rrf": contribution}
            if result.get("text"):
                fused[identifier]["text"] = result["text"]
    return sorted(fused.values(), key=lambda row: (-row["score"], row["keyframe_id"]))


def temporal_pairs(first: list[dict], second: list[dict], min_gap_ms: int = 1, max_gap_ms: int = 30000, top_k: int = 24) -> list[dict]:
    """Ghép trong candidate/video bằng binary search; tuyệt đối B>A.

    Không tạo ma trận NxN toàn kho. Hai tập ứng viên được giới hạn upstream;
    score trung bình rank-score A/B, giữ riêng evidence của hai sự kiện.
    """
    if min_gap_ms < 0 or max_gap_ms <= 0 or min_gap_ms > max_gap_ms:
        raise ValueError("Khoảng gap temporal không hợp lệ.")
    grouped = defaultdict(list)
    for row in second:
        grouped[row["video_uid"]].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: (row["timestamp_ms"], row["keyframe_id"]))
    timeline = {uid: [row["timestamp_ms"] for row in rows] for uid, rows in grouped.items()}
    winners = []
    for left in first:
        rows = grouped.get(left["video_uid"], [])
        times = timeline.get(left["video_uid"], [])
        low = bisect_left(times, left["timestamp_ms"] + max(1, min_gap_ms))
        high = bisect_right(times, left["timestamp_ms"] + max_gap_ms)
        for right in rows[low:high]:
            gap = right["timestamp_ms"] - left["timestamp_ms"]
            winners.append(dict(left, score=(left["score"] + right["score"]) / 2, pair={"keyframe_id": right["keyframe_id"], "timestamp_ms": right["timestamp_ms"], "gap_ms": gap}, contributions={"event_a": left.get("contributions", {}), "event_b": right.get("contributions", {})}))
        # Giữ heap/top-k nhỏ giữa từng A; RAM không tăng theo số cặp.
        winners = sorted(winners, key=lambda row: (-row["score"], row["keyframe_id"], row["pair"]["keyframe_id"]))[:top_k]
    return winners


class RetrievalService:
    """Resolve keyframe từ DB và hợp nhất channel với cùng anchor ID."""
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self._index = None
        self._encoder = None
        self._pointer = None
        self._error = None
        self._lock = RLock()

    def _load_index(self):
        """Refresh khi CURRENT thay đổi; lỗi integrity làm channel unavailable."""
        pointer = self.settings.index_root / "CURRENT"
        try:
            marker = pointer.read_text(encoding="utf-8").strip() if pointer.exists() else None
        except OSError:
            self._error = "Không thể đọc index hiện tại; kiểm tra file CURRENT và quyền truy cập local."
            return None
        if marker is None:
            return None
        with self._lock:
            if marker != self._pointer:
                self._pointer = marker
                self._index, self._encoder, self._error = None, None, None
                try:
                    self._index = NumpyShardIndex(self.settings.index_root)
                    self._encoder = encoder_for_manifest(self.settings, self._index.manifest)
                except (ValueError, OSError, KeyError) as error:
                    # Một adapter fail không được để index/encoder thành pair nửa vời.
                    # OSError có thể chứa absolute path; response chỉ giải thích nghiệp vụ.
                    self._index, self._encoder = None, None
                    self._error = "File index/manifest/shard thiếu hoặc không thể đọc; kiểm tra dữ liệu local rồi chạy index lại." if isinstance(error, OSError) else str(error)
            if self._index is not None:
                # Kiểm tra ledger nhỏ thay vì băm toàn mapping mỗi query. Extraction
                # hoàn tất sau lần index gần nhất nghĩa derived IDs đã invalidated.
                revision = self.db.one("SELECT MAX(CASE WHEN kind='extract' THEN rowid ELSE 0 END) AS extraction,MAX(CASE WHEN kind='index' THEN rowid ELSE 0 END) AS indexing FROM jobs WHERE status='completed'")
                if revision and (revision["indexing"] or 0) > 0 and (revision["extraction"] or 0) > revision["indexing"]:
                    self._error = "Keyframes đã đổi sau phiên bản index hiện tại; chạy embed rồi index trước khi tìm visual."
                    return None
            return self._index

    def capabilities(self) -> dict:
        """Capability dựa trên index/weights/text thực; chưa inference semantic."""
        index = self._load_index()
        visual = bool(index is not None and self._encoder.available)
        image_allowed = not (self.settings.contest_mode and self.settings.task_type == "video_kis")
        ocr = bool(self.db.one("SELECT 1 FROM text_segments WHERE source='ocr' LIMIT 1"))
        asr = bool(self.db.one("SELECT 1 FROM text_segments WHERE source='asr' LIMIT 1"))
        reasons = {}
        if not visual:
            reasons["visual_text"] = self._error or ("Chưa có index." if index is None else "Chưa có weights OpenCLIP local.")
        if not image_allowed:
            reasons["image"] = "Video KIS contest chặn image upload và query-by-example theo profile 2024."
        if not ocr:
            reasons["ocr"] = "Chưa import hoặc trích OCR thực."
        if not asr:
            reasons["asr"] = "Chưa import hoặc trích ASR thực."
        return {"modes": {"visual_text": visual, "image": visual and image_allowed, "ocr": ocr, "asr": asr, "hybrid": visual or ocr or asr, "temporal": visual or ocr or asr}, "reasons": reasons, "contest_mode": self.settings.contest_mode, "task_type": self.settings.task_type, "index_version": index.version if index else None, "encoder_id": index.encoder_id if index else None, "fixture": bool(index and index.manifest.get("fixture"))}

    def _rows(self, request: dict) -> list[dict]:
        clauses, values = [], []
        if request.get("keyframe_ids") is not None:
            if not request["keyframe_ids"]:
                return []
            clauses.append("k.keyframe_id IN (" + ",".join("?" for _ in request["keyframe_ids"]) + ")")
            values.extend(request["keyframe_ids"])
        if request.get("video_uids"):
            clauses.append("k.video_uid IN (" + ",".join("?" for _ in request["video_uids"]) + ")")
            values.extend(request["video_uids"])
        for field, operator in (("start_ms", ">="), ("end_ms", "<=")):
            if request.get(field) is not None:
                clauses.append(f"k.timestamp_ms{operator}?")
                values.append(request[field])
        statement = "SELECT k.*,v.media_item_name FROM keyframes k JOIN videos v USING(video_uid)"
        return self.db.rows(statement + (" WHERE " + " AND ".join(clauses) if clauses else ""), values)

    @staticmethod
    def _result(row: dict, score: float, contributions: dict | None = None) -> dict:
        """Response chỉ có URL qua ID; không có absolute/relative filesystem path."""
        return {"keyframe_id": row["keyframe_id"], "video_uid": row["video_uid"], "media_item_name": row["media_item_name"], "timestamp_ms": int(row["timestamp_ms"]), "thumbnail_url": f"/api/media/thumbnail/{row['keyframe_id']}", "video_url": f"/api/media/video/{row['video_uid']}", "score": float(score), "contributions": contributions or {}}

    def _visual(self, query: str, request: dict, rows: list[dict] | None) -> list[dict]:
        index = self._load_index()
        if index is None:
            raise EncoderUnavailable(self._error or "Chưa có visual index.")
        with self._lock:
            vector = self._encoder.encode_text(query)
            if self._encoder.metadata["encoder_id"] != index.encoder_id:
                raise EncoderUnavailable("Weights/preprocessing của query khác encoder index; cần re-encode.")
            if request.get("use_feedback"):
                feedback = self.db.rows("SELECT keyframe_id,relevant FROM feedback WHERE session_id=?", (request.get("feedback_session", "default"),))
                positive, negative = [], []
                for item in feedback:
                    if item["keyframe_id"] in index.locations:
                        (positive if item["relevant"] else negative).append(index.vector(item["keyframe_id"]))
                vector = np.array(vector, dtype=np.float32)
                if positive:
                    vector += .75 * np.mean(positive, axis=0)
                if negative:
                    vector -= .25 * np.mean(negative, axis=0)
                vector = normalize(vector)
        limit = min(2000, max(100, int(request.get("top_k", 24)) * 8))
        allowed = {row["keyframe_id"] for row in rows} if rows is not None else None
        matches = index.search(vector, limit, allowed)
        by_id = {row["keyframe_id"]: row for row in self._rows({"keyframe_ids": [identifier for identifier, _ in matches]})}
        return [self._result(by_id[identifier], score, {"visual": {"cosine": score}}) for identifier, score in matches if identifier in by_id]

    def _text(self, query: str, source: str, request: dict, rows: list[dict] | None) -> list[dict]:
        limit = min(2000, max(100, int(request.get("top_k", 24)) * 8))
        segments = search_database(self.db, query, source, limit, video_uids=request.get("video_uids"), start_ms=request.get("start_ms"), end_ms=request.get("end_ms"))
        winners = {}
        with self.db.connection() as connection:
            for segment, score in segments:
                start, end = segment["start_ms"], segment["end_ms"]
                conditions = ["k.video_uid=?", "k.timestamp_ms BETWEEN ? AND ?"]
                parameters = [segment["video_uid"], start, end]
                for field, operator in (("start_ms", ">="), ("end_ms", "<=")):
                    if request.get(field) is not None:
                        conditions.append(f"k.timestamp_ms{operator}?")
                        parameters.append(request[field])
                base = "SELECT k.*,v.media_item_name FROM keyframes k JOIN videos v USING(video_uid) WHERE "
                matching = [dict(row) for row in connection.execute(base + " AND ".join(conditions) + " ORDER BY k.timestamp_ms LIMIT ?", parameters + [limit])]
                if not matching:
                    # Tìm quanh biên theo index timeline; không quét toàn video.
                    conditions = ["k.video_uid=?", "k.timestamp_ms BETWEEN ? AND ?"]
                    parameters = [segment["video_uid"], max(0, start - 1000), end + 1000]
                    for field, operator in (("start_ms", ">="), ("end_ms", "<=")):
                        if request.get(field) is not None:
                            conditions.append(f"k.timestamp_ms{operator}?")
                            parameters.append(request[field])
                    statement = base + " AND ".join(conditions) + " ORDER BY MIN(ABS(k.timestamp_ms-?),ABS(k.timestamp_ms-?)),k.timestamp_ms LIMIT 1"
                    matching = [dict(row) for row in connection.execute(statement, parameters + [start, end])]
                for row in matching:
                    identifier = row["keyframe_id"]
                    if identifier not in winners or score > winners[identifier]["score"]:
                        result = self._result(row, score, {source: {"bm25": score, "segment_id": segment["segment_id"], "start_ms": start, "end_ms": end}})
                        result["text"] = segment["text"]
                        winners[identifier] = result
        return sorted(winners.values(), key=lambda row: (-row["score"], row["keyframe_id"]))[:limit]

    def _channels(self, query: str, request: dict, rows: list[dict], warnings: list[str]) -> dict:
        channels = {}
        capabilities = self.capabilities()["modes"]
        if capabilities["visual_text"] and request.get("weights", {}).get("visual", 1) > 0:
            try:
                channels["visual"] = self._visual(request.get("visual_query") or query, request, rows)
            except EncoderUnavailable as error:
                warnings.append(str(error))
        for source in ("ocr", "asr"):
            if capabilities[source] and request.get("weights", {}).get(source, 1) > 0:
                channels[source] = self._text(query, source, request, rows)
        return channels

    def search(self, request: dict) -> dict:
        """Tìm mode typed; temporal tìm A/B độc lập trong cùng filter.

        Raises EncoderUnavailable nếu yêu cầu kênh chưa có, ValueError nếu grammar
        sai. Expansion là term người dùng cung cấp, không tự sinh/dịch.
        """
        started = time.perf_counter()
        mode, warnings = request.get("mode", "visual_text"), []
        query = request["query"].strip()
        if not query:
            raise ValueError("Query không được rỗng.")
        if request.get("expansion"):
            expansion = " OR ".join('"' + value.replace('"', '') + '"' for value in request["expansion"] if value.strip())
            if mode in ("ocr", "asr", "hybrid", "temporal") and expansion:
                query = f"({query}) OR ({expansion})"
            elif expansion:
                query += " " + " ".join(request["expansion"])
        # Chỉ materialize metadata khi có filter; unfiltered query resolve top-k.
        rows = self._rows(request) if request.get("video_uids") or request.get("start_ms") is not None or request.get("end_ms") is not None else None
        if mode == "visual_text":
            results = self._visual(request.get("visual_query") or query, request, rows)
        elif mode in ("ocr", "asr"):
            if not self.capabilities()["modes"][mode]:
                raise EncoderUnavailable(f"Chưa có dữ liệu {mode.upper()}.")
            results = self._text(query, mode, request, rows)
        elif mode in ("hybrid", "temporal"):
            channels = self._channels(query, request, rows, warnings)
            if not channels:
                raise EncoderUnavailable("Không có kênh khả dụng cho hybrid/temporal.")
            first = weighted_rrf(channels, request.get("weights", {}))
            if mode == "temporal":
                if not request.get("query_b", "").strip():
                    raise ValueError("Temporal cần query_b.")
                second_request = dict(request, visual_query=None)
                second = weighted_rrf(self._channels(request["query_b"], second_request, rows, warnings), request.get("weights", {}))
                results = temporal_pairs(first, second, request.get("min_gap_ms", 1), request.get("max_gap_ms", 30000), request.get("top_k", 24))
            else:
                results = first
        else:
            raise ValueError("Mode tìm kiếm không được hỗ trợ.")
        if request.get("group_by_video"):
            seen = set()
            results = [row for row in results if not (row["video_uid"] in seen or seen.add(row["video_uid"]))]
        results = results[:request.get("top_k", 24)]
        for rank, row in enumerate(results, 1):
            row["rank"] = rank
        index = self._load_index()
        if index and index.manifest.get("fixture"):
            warnings.append("Kết quả trên fixture tổng hợp; không phải benchmark semantic của dataset thật.")
        return {"results": results, "elapsed_ms": (time.perf_counter() - started) * 1000, "index_version": index.version if index else None, "warnings": warnings}

    def _image_allowed(self):
        if self.settings.contest_mode and self.settings.task_type == "video_kis":
            raise PermissionError("Video KIS contest chặn truy vấn ảnh theo profile AIC2024.")

    def search_image(self, image_bytes: bytes, top_k: int = 24) -> dict:
        """Decode ảnh upload giới hạn size/pixel rồi encode cùng space index."""
        self._image_allowed()
        started = time.perf_counter()
        if len(image_bytes) > 12 * 1024 * 1024:
            raise ValueError("Ảnh vượt giới hạn 12 MiB.")
        index = self._load_index()
        if index is None:
            raise EncoderUnavailable("Chưa có visual index.")
        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                if image.width * image.height > 30_000_000:
                    raise ValueError("Ảnh vượt 30 triệu pixel.")
                with self._lock:
                    vector = self._encoder.encode_images([image.convert("RGB")])[0]
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError("Upload không phải ảnh hợp lệ.") from error
        if self._encoder.metadata["encoder_id"] != index.encoder_id:
            raise EncoderUnavailable("Image encoder không khớp index.")
        return self._vector_response(vector, top_k, started)

    def _vector_response(self, vector: np.ndarray, top_k: int, started: float) -> dict:
        index = self._load_index()
        matches = index.search(vector, top_k)
        rows = {row["keyframe_id"]: row for row in self._rows({"keyframe_ids": [identifier for identifier, _ in matches]})}
        results = [self._result(rows[identifier], score, {"visual": {"cosine": score}}) for identifier, score in matches if identifier in rows]
        return {"results": results, "elapsed_ms": (time.perf_counter() - started) * 1000, "index_version": index.version, "warnings": ["Fixture tổng hợp; chỉ kiểm tra contract."] if index.manifest.get("fixture") else []}

    def search_example(self, keyframe_id: str, top_k: int = 24) -> dict:
        """Lấy vector đã lưu, giữ nguyên space; contest chặn cả endpoint này."""
        self._image_allowed()
        started = time.perf_counter()
        index = self._load_index()
        if index is None:
            raise EncoderUnavailable("Chưa có visual index.")
        return self._vector_response(index.vector(keyframe_id), top_k, started)
