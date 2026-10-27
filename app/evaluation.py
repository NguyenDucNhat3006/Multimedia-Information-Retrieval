"""Đánh giá offline ở mức event với nhãn người gán; không suy relevance từ cosine hay fixture."""

from pathlib import Path
import hashlib
import json
import math
import platform
import time
import uuid
import numpy as np
from pydantic import BaseModel, Field, model_validator


LABEL_SCHEMA = {
    "provenance": "human_reviewed", "split": "test",
    "queries": [{"query_id": "q1", "query": "a person on a bicycle", "mode": "visual_text",
                 "exhaustive_judgments": False,
                 "events": [{"event_id": "e1", "video_uid": "ID từ /api/data", "start_ms": 1000,
                             "end_ms": 3000, "grade": 1}]}],
}


class EventLabel(BaseModel):
    """Một event được đánh giá một lần dù có nhiều keyframe nằm trong interval ms."""
    event_id: str = Field(min_length=1)
    video_uid: str = Field(min_length=1)
    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(ge=0, strict=True)
    grade: int = Field(ge=0, le=4, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        """Từ chối interval ngược, không đoán đơn vị giây từ số nhỏ."""
        if self.end_ms < self.start_ms:
            raise ValueError("Nhãn end_ms phải >= start_ms")
        return self


class QueryLabels(BaseModel):
    """Query giữ split và relevance; exhaustive cần true mới công bố AP/mAP."""
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    mode: str = "visual_text"
    visual_query: str | None = None
    query_b: str | None = None
    exhaustive_judgments: bool = False
    events: list[EventLabel] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_events(self):
        """Nhãn event trùng/overlap khiến một frame có hai relevance, phải sửa trước benchmark."""
        from .schemas import SearchRequest
        SearchRequest(mode=self.mode, query=self.query, query_b=self.query_b, visual_query=self.visual_query)
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("event_id phải duy nhất trong query")
        for i, event in enumerate(self.events):
            for other in self.events[i + 1:]:
                if event.video_uid == other.video_uid and max(event.start_ms, other.start_ms) <= min(event.end_ms, other.end_ms):
                    raise ValueError("Các interval relevance không được chồng lấn trong cùng video/query")
        if not any(event.grade > 0 for event in self.events):
            raise ValueError("Query benchmark cần ít nhất một event relevant")
        return self


class LabelSet(BaseModel):
    """Provenance phân biệt fixture minh họa với bộ nhãn có người kiểm duyệt."""
    provenance: str
    split: str
    queries: list[QueryLabels] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_queries(self):
        """Không gộp lặp một query làm sai trung bình macro."""
        if len({q.query_id for q in self.queries}) != len(self.queries):
            raise ValueError("query_id phải duy nhất")
        if self.provenance not in {"human_reviewed", "labelled_fixture"}:
            raise ValueError("provenance phải là human_reviewed hoặc labelled_fixture")
        if self.split not in {"train", "dev", "test"}:
            raise ValueError("split phải là train/dev/test")
        return self


def save_labels(payload: dict, path: Path, db) -> dict:
    """Validate nhãn đối chiếu duration thực trước khi publish file nguyên tử; không dùng để tune test."""
    labels = LabelSet.model_validate(payload)
    for query in labels.queries:
        for event in query.events:
            video = db.one("SELECT duration_ms FROM videos WHERE video_uid=?", (event.video_uid,))
            if video is None or event.end_ms > video["duration_ms"]:
                raise ValueError("Nhãn có video không tồn tại hoặc interval vượt duration")
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    staging.write_text(labels.model_dump_json(indent=2), encoding="utf-8")
    staging.replace(path)
    return {"status": "saved", "queries": len(labels.queries), "provenance": labels.provenance, "split": labels.split}


def metrics_at_k(results: list[dict], events: list[EventLabel | dict], k: int, exhaustive: bool = False) -> dict:
    """Tính P/R/MRR/nDCG theo query; frame thứ hai của event đã hit không được tính thêm gain.

    Precision@K dùng mẫu số K (thiếu kết quả là slot không relevant). Recall là số event
    relevant tìm được / tổng event relevant. AP@K là truncated AP, chỉ có nhãn exhaustive.
    """
    if type(k) is not int or k < 1:
        raise ValueError("K phải là integer dương")
    labels = [e if isinstance(e, EventLabel) else EventLabel.model_validate(e) for e in events]
    relevant = sum(e.grade > 0 for e in labels)
    seen = set()
    hit_count = 0
    first_hit = 0
    ap_sum = 0.0
    dcg = 0.0
    for rank, result in enumerate(results[:k], start=1):
        match = next((e for e in labels if e.video_uid == result["video_uid"] and
                      e.start_ms <= result["timestamp_ms"] <= e.end_ms), None)
        if match and match.event_id not in seen:
            seen.add(match.event_id)
            if match.grade > 0:
                hit_count += 1
                first_hit = first_hit or rank
                ap_sum += hit_count / rank
                dcg += (2 ** match.grade - 1) / math.log2(rank + 1)
    ideal = sorted((e.grade for e in labels if e.grade > 0), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal, start=1))
    return {f"Precision@{k}": hit_count / k, f"Recall@{k}": hit_count / relevant if relevant else 0,
            "RR": 1 / first_hit if first_hit else 0, f"nDCG@{k}": dcg / idcg if idcg else 0,
            f"AP@{k}": ap_sum / relevant if exhaustive and relevant else None}


def evaluate_file(labels_path: Path | str, settings, top_k: int = 10, output_path: Path | str | None = None) -> dict:
    """Chạy retrieval thực cho từng query, lưu latency warm/cold và hash nhãn; không gọi DRES.

    Args: labels_path là JSON nhãn đã kiểm duyệt; top_k >=1, output_path report tùy chọn.
    Returns: macro metrics theo event/query và kết quả từng query để phân tích lỗi.
    """
    from .db import Database
    from .retrieval import RetrievalService
    from .schemas import SearchRequest
    if top_k < 1 or top_k > 200:
        raise ValueError("top_k benchmark trong [1,200]")
    content = Path(labels_path).read_bytes()
    labels = LabelSet.model_validate_json(content)
    db = Database(settings.db_path)
    for query in labels.queries:
        for event in query.events:
            row = db.one("SELECT duration_ms FROM videos WHERE video_uid=?", (event.video_uid,))
            if row is None or event.end_ms > row["duration_ms"]:
                raise ValueError("Nhãn benchmark thiếu video hoặc vượt duration")
    service = RetrievalService(db, settings)
    entries, latency = [], []
    for query in labels.queries:
        request = SearchRequest(mode=query.mode, query=query.query, visual_query=query.visual_query,
                                query_b=query.query_b, top_k=top_k).model_dump()
        started = time.perf_counter()
        result = service.search(request)
        elapsed = (time.perf_counter() - started) * 1000
        latency.append(elapsed)
        entries.append({"query_id": query.query_id, "query": query.query, "mode": query.mode,
                        "metrics": metrics_at_k(result["results"], query.events, top_k, query.exhaustive_judgments),
                        "elapsed_ms": elapsed, "results": result["results"], "warnings": result.get("warnings", [])})
    keys = entries[0]["metrics"].keys()
    macro = {key: float(np.mean([e["metrics"][key] for e in entries]))
             if all(e["metrics"][key] is not None for e in entries) else None for key in keys}
    macro["MRR"] = macro.pop("RR")
    macro[f"mAP@{top_k}"] = macro.pop(f"AP@{top_k}")
    caps = service.capabilities()
    report = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "provenance": labels.provenance, "fixture": caps.get("fixture", False), "split": labels.split,
              "label_sha256": hashlib.sha256(content).hexdigest(), "query_count": len(entries), "top_k": top_k,
              "metrics": macro, "latency_ms": {"cold_first": latency[0],
                  "warm_p50": float(np.percentile(latency[1:], 50)) if len(latency) > 1 else None,
                  "warm_p95": float(np.percentile(latency[1:], 95)) if len(latency) > 1 else None,
                  "p50": float(np.percentile(latency, 50)), "p95": float(np.percentile(latency, 95))},
              "hardware": {"platform": platform.platform(), "processor": platform.processor(), "device": settings.device},
              "index_version": caps.get("index_version"), "results": entries,
              "protocol": "event recall; duplicate frames gain=0; Precision denominator=K; no test tuning; mAP@K requires exhaustive judgments"}
    output = Path(output_path) if output_path else settings.data_root / "evaluation" / f"report-{time.time_ns()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
