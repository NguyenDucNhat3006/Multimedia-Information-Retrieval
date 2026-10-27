"""Hồi quy retrieval: space identity, shard integrity, Boolean và temporal ms."""
import json
from dataclasses import replace

import numpy as np
import pytest

from app.config import Settings
from app.db import Database
from app.encoders import EncoderUnavailable, FixtureEncoder
from app.index import NumpyShardIndex, normalize, publish_index
from app.retrieval import RetrievalService, temporal_pairs, weighted_rrf
from app.text_search import BooleanParser, TextIndex, search_database


def publish_fixture(root, ids=None, vectors=None):
    """Vector kiểm chứng được bằng tay, không cần weights/network."""
    return publish_index(root, [(ids or ["a", "b", "c"], np.array(vectors if vectors is not None else [[1, 0, 0, 0], [.6, .8, 0, 0], [0, 1, 0, 0]], dtype=np.float32))], FixtureEncoder.metadata, dataset_fingerprint="dataset", keyframe_fingerprint="frames", shard_size=2)


def test_exact_cosine_filter_before_topk_and_persistent_mapping(tmp_path):
    """Post-filter top-k sai có thể bỏ hết kết quả hợp lệ; filter phải đi trước."""
    manifest = publish_fixture(tmp_path)
    index = NumpyShardIndex(tmp_path, expected_encoder_id="fixture-colors-v1")
    assert len(manifest["shards"]) == 2
    assert index.search(np.array([1, 0, 0, 0]), 3) == [("a", 1.0), ("b", pytest.approx(.6)), ("c", 0.0)]
    assert index.search(np.array([1, 0, 0, 0]), 1, {"c"}) == [("c", 0.0)]
    assert np.array_equal(index.vector("b"), np.array([.6, .8, 0, 0], dtype=np.float32))
    copied = index.vector("a")
    copied[0] = 0
    assert index.vector("a")[0] == 1


def test_same_dimension_encoder_mismatch_and_corrupt_shard(tmp_path):
    """Dimension bằng nhau không chứng minh checkpoint/preprocessing bằng nhau."""
    manifest = publish_fixture(tmp_path)
    with pytest.raises(ValueError, match="Encoder mismatch"):
        NumpyShardIndex(tmp_path, expected_encoder_id="different-checkpoint-same-D")
    shard = tmp_path / "versions" / manifest["version"] / manifest["shards"][0]["vectors"]
    with shard.open("r+b") as stream:
        stream.seek(-4, 2)
        stream.write(b"xxxx")
    with pytest.raises(ValueError, match="Shard hỏng"):
        NumpyShardIndex(tmp_path)


def test_missing_mapping_and_failed_publication_preserve_current(tmp_path):
    """Index staging lỗi không làm mất phiên bản đã commit trước đó."""
    manifest = publish_fixture(tmp_path)
    before = (tmp_path / "CURRENT").read_text()
    with pytest.raises(ValueError, match="Duplicate"):
        publish_fixture(tmp_path, ["same", "same"], [[1, 0, 0, 0], [1, 0, 0, 0]])
    assert (tmp_path / "CURRENT").read_text() == before
    mapping = tmp_path / "versions" / manifest["version"] / manifest["shards"][0]["mapping"]
    mapping.unlink()
    with pytest.raises(ValueError, match="thiếu mapping"):
        NumpyShardIndex(tmp_path)


def test_normalize_rejects_nan_zero_and_dimension(tmp_path):
    """NaN/zero âm thầm vào index sẽ làm thứ hạng không tái hiện được."""
    for invalid in ([0, 0], [float("nan"), 1]):
        with pytest.raises(ValueError):
            normalize(np.array(invalid))
    publish_fixture(tmp_path)
    with pytest.raises(ValueError, match="dimension"):
        NumpyShardIndex(tmp_path).search(np.array([1, 0]), 1)


@pytest.fixture
def documents():
    return [{"segment_id": "1", "text": "xe đỏ chạy trên đường"}, {"segment_id": "2", "text": "xe xanh dừng trên đường"}, {"segment_id": "3", "text": "đỏ xe tàu"}]


def test_unicode_boolean_phrase_precedence_and_tfidf(documents):
    """Phrase giữ vị trí token; AND có precedence cao hơn OR, dấu được giữ."""
    index = TextIndex(documents)
    assert {row["segment_id"] for row, _ in index.search('"xe đỏ"')} == {"1"}
    assert {row["segment_id"] for row, _ in index.search("đỏ AND NOT tàu")} == {"1"}
    assert {row["segment_id"] for row, _ in index.search("đỏ OR xanh AND dừng")} == {"1", "2", "3"}
    assert index.search("do") == []
    assert index.search('"xe đỏ"', method="tfidf")[0][1] > 0
    assert {row["segment_id"] for row, _ in index.search("NOT đỏ")} == {"2"}
    for malformed in ('"xe', "xe AND", "(xe OR đỏ", "xe )", "OR xe"):
        with pytest.raises(ValueError):
            BooleanParser(malformed).parse()


def _temporal_row(identifier, uid, timestamp, score=1):
    return {"keyframe_id": identifier, "video_uid": uid, "timestamp_ms": timestamp, "score": score, "contributions": {}}


def test_temporal_same_video_strict_order_and_inclusive_ms_boundaries():
    """B trước A hoặc khác video không thể thành cặp dù cosine cao."""
    first = [_temporal_row("a", "v1", 12000)]
    second = [_temporal_row("before", "v1", 11000), _temporal_row("equal", "v1", 12000), _temporal_row("other", "v2", 13000), _temporal_row("low", "v1", 13000), _temporal_row("high", "v1", 15000), _temporal_row("beyond", "v1", 15001)]
    matches = temporal_pairs(first, second, 1000, 3000)
    assert {row["pair"]["keyframe_id"] for row in matches} == {"low", "high"}
    assert {row["pair"]["gap_ms"] for row in matches} == {1000, 3000}
    assert temporal_pairs([], second) == []
    assert temporal_pairs(first, [], 0, 3000) == []
    assert all(row["pair"]["gap_ms"] > 0 for row in temporal_pairs(first, second, 0, 3000))


def test_rrf_scores_rank_not_raw_scale():
    """BM25 rất lớn không thể áp đảo cosine chỉ vì khác thang điểm."""
    visual = [_temporal_row("a", "v", 0, .9), _temporal_row("b", "v", 1, .8)]
    ocr = [_temporal_row("b", "v", 1, 1000000)]
    results = weighted_rrf({"visual": visual, "ocr": ocr}, {"visual": 1, "ocr": 2})
    assert results[0]["keyframe_id"] == "b"
    assert results[0]["score"] == pytest.approx(1 / 62 + 2 / 61)
    assert results[0]["contributions"]["ocr"]["raw_score"] == 1000000


@pytest.fixture
def service(tmp_path):
    """Ba frame và segment local có khoảng thời gian khai báo, không model giả thật."""
    settings = Settings(tmp_path, tmp_path / "metadata.sqlite3", tmp_path / "index")
    db = Database(settings.db_path)
    db.upsert_video({"video_uid": "v", "media_item_name": "TEST", "source_batch": "fixture", "relative_path": "media/test.mp4", "duration_ms": 10000, "fingerprint": "fixture"})
    for identifier, timestamp in (("a", 0), ("b", 4000), ("c", 9000)):
        db.upsert_keyframe({"keyframe_id": identifier, "video_uid": "v", "timestamp_ms": timestamp, "thumbnail_path": f"thumb/{identifier}.jpg", "timestamp_source": "fixture", "encoder_id": "fixture-colors-v1"})
    db.import_text([{"segment_id": "s1", "video_uid": "v", "start_ms": 3900, "end_ms": 4500, "source": "ocr", "text": "xe đỏ đang chạy"}, {"segment_id": "s2", "video_uid": "v", "start_ms": 8000, "end_ms": 8500, "source": "asr", "text": "xanh"}])
    publish_fixture(settings.index_root)
    return RetrievalService(db, settings)


def test_database_boolean_not_phrase_and_bm25(service):
    """Production SQL grammar phải khớp baseline, NOT-only không gọi MATCH sai."""
    assert search_database(service.db, '"xe đỏ" AND NOT dừng', "ocr")[0][0]["segment_id"] == "s1"
    assert search_database(service.db, "NOT dừng", "ocr")[0][0]["segment_id"] == "s1"
    assert search_database(service.db, "NOT đỏ", "ocr") == []
    assert search_database(service.db, '"xe đỏ"', "asr") == []


def test_text_anchor_filter_feedback_and_contest_image_gate(service):
    """ASR/OCR chỉ map đúng interval/biên gần, không gán mọi frame video."""
    result = service.search({"mode": "ocr", "query": "đỏ", "top_k": 10})
    assert [row["keyframe_id"] for row in result["results"]] == ["b"]
    assert service.search({"mode": "ocr", "query": "đỏ", "start_ms": 5000, "top_k": 10})["results"] == []
    service.db.execute("INSERT INTO feedback(session_id,keyframe_id,relevant) VALUES('s','c',1)")
    before = service._load_index().vector("c")
    service.search({"mode": "visual_text", "query": "red", "top_k": 3, "use_feedback": True, "feedback_session": "s"})
    assert np.array_equal(before, service._load_index().vector("c"))
    blocked = RetrievalService(service.db, replace(service.settings, contest_mode=True, task_type="video_kis"))
    assert blocked.capabilities()["modes"]["image"] is False
    with pytest.raises(PermissionError):
        blocked.search_image(b"invalid")
    with pytest.raises(PermissionError):
        blocked.search_example("a")


def test_invalid_fixture_encoder_keeps_capabilities_available_and_safe(service):
    """Adapter fail phải clear pair; capability không crash vì encoder None."""
    encoder = dict(FixtureEncoder.metadata, encoder_id="unknown-fixture-encoder")
    publish_index(service.settings.index_root, [(["a"], np.array([[1, 0, 0, 0]], dtype=np.float32))], encoder, dataset_fingerprint="dataset", keyframe_fingerprint="frames")
    capabilities = service.capabilities()
    assert capabilities["modes"]["visual_text"] is False
    assert capabilities["modes"]["ocr"] is True
    assert "Fixture encoder" in capabilities["reasons"]["visual_text"]
    assert service._index is None and service._encoder is None


def test_missing_index_files_do_not_expose_absolute_paths(service):
    """OSError chứa tên ổ/path không được đưa vào capability hoặc API error."""
    (service.settings.index_root / "CURRENT").write_text("missing-version", encoding="utf-8")
    capabilities = service.capabilities()
    assert capabilities["modes"]["visual_text"] is False
    assert str(service.settings.data_root) not in json.dumps(capabilities)
    with pytest.raises(EncoderUnavailable) as caught:
        service.search({"mode": "visual_text", "query": "red"})
    assert str(service.settings.data_root) not in str(caught.value)


def test_new_extraction_invalidates_visual_readiness_until_reindex(service):
    """CURRENT chưa đổi nhưng extraction đổi mapping: không quảng cáo visual ready."""
    service.db.execute("INSERT INTO jobs(job_id,kind,status) VALUES('index-old','index','completed')")
    assert service.capabilities()["modes"]["visual_text"] is True
    service.db.execute("INSERT INTO jobs(job_id,kind,status) VALUES('extract-new','extract','completed')")
    capabilities = service.capabilities()
    assert capabilities["modes"]["visual_text"] is False
    assert capabilities["modes"]["ocr"] is True
    with pytest.raises(EncoderUnavailable, match="Keyframes đã đổi"):
        service.search({"mode": "visual_text", "query": "red"})
    service.db.execute("INSERT INTO jobs(job_id,kind,status) VALUES('index-new','index','completed')")
    assert service.capabilities()["modes"]["visual_text"] is True
