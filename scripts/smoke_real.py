"""Smoke local có media/model/index thật; không tạo nhãn hoặc metric chất lượng retrieval."""

from pathlib import Path
import json
import sys
import time

from app.config import Settings
from app.db import Database
from app.pipeline import extract_video, embed_dataset, build_index, doctor, inspect_data
from fastapi.testclient import TestClient
from app.main import create_app


def main():
    """Đọc hai video được chọn, kiểm thử request thật và lưu evidence trong docs/reports."""
    import torch
    torch.set_num_threads(4)
    settings = Settings.from_env()
    db = Database(settings.db_path)
    reports = Path(__file__).resolve().parents[1] / "docs" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    inventory = {
        "inspected_at": "2026-10-14", "sources": [
            inspect_data(r"E:\batch2.zip", reports / "inventory-batch2.json"),
            inspect_data(r"E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1", reports / "inventory-batch1.json")],
        "provenance": "local ZIP64 central directory and local filesystem stat; no whole archive extraction"}
    (reports.parent.parent / "data_inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    hardware = doctor(settings)
    (reports / "doctor.json").write_text(json.dumps(hardware, ensure_ascii=False, indent=2), encoding="utf-8")
    extracted = []
    for name, maximum in (("L02_V020.mp4", 48), ("L05_V021.mp4", 24)):
        result = extract_video(db, settings, Path(r"E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1") / name,
                               source_batch="batch1", interval_ms=2000, max_frames=maximum)
        extracted.append(result)
        print(json.dumps({"extract": result}, ensure_ascii=False), flush=True)
    embeddings = embed_dataset(db, settings, batch_size=8)
    print(json.dumps({"embedded_rows": embeddings["row_count"], "reused_rows": embeddings["reused_rows"]}), flush=True)
    manifest = build_index(db, settings)
    queries = []
    with TestClient(create_app(settings)) as client:
        for query in ("a television news presenter", "people outdoors", "a green field"):
            started = time.perf_counter()
            response = client.post("/api/search", json={"mode": "visual_text", "query": query, "top_k": 8})
            if response.status_code != 200:
                raise RuntimeError(response.text)
            result = response.json()
            assert len(result["results"]) == 8
            first = result["results"][0]
            assert client.get(first["thumbnail_url"]).status_code == 200
            partial = client.get(first["video_url"], headers={"Range": "bytes=0-1023"})
            assert partial.status_code == 206 and len(partial.content) == 1024
            queries.append({"query": query, "wall_ms": (time.perf_counter() - started) * 1000, **result})
        uid = extracted[0]["video_uid"]
        filtered = client.post("/api/search", json={"mode": "visual_text", "query": "people", "top_k": 5,
                                                    "video_uids": [uid], "start_ms": 10000, "end_ms": 20000}).json()
        assert all(r["video_uid"] == uid and 10000 <= r["timestamp_ms"] <= 20000 for r in filtered["results"])
        example = client.post("/api/search/example", json={"keyframe_id": queries[0]["results"][0]["keyframe_id"], "top_k": 5})
        assert example.status_code == 200
        temporal = client.post("/api/search", json={"mode": "temporal", "query": "people", "query_b": "a news presenter", "max_gap_ms": 10000, "top_k": 5})
        assert temporal.status_code == 200, temporal.text
        for row in temporal.json()["results"]:
            assert 0 < row["pair"]["gap_ms"] <= 10000
    report = {"provenance": "real local batch1 videos + real OpenCLIP weights + NumPy index; NOT a relevance benchmark",
              "hardware": hardware, "extraction": extracted, "embedding": embeddings, "index": manifest,
              "queries": queries, "filter_results": filtered, "example_status": example.status_code,
              "temporal_results": temporal.json(), "ground_truth": "not available; semantic relevance quality not measured",
              "checks": ["real PTS extraction", "real CPU image/text embedding", "real exact search", "8 results each",
                         "filter before top-k", "thumbnail", "video byte range", "query-by-example", "temporal gap contract"]}
    (reports / "smoke-real.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REAL SMOKE PASS: docs/reports/smoke-real.json", flush=True)


if __name__ == "__main__":
    main()
