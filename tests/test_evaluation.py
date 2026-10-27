"""Metric theo event ngăn inflate recall bằng nhiều keyframe gần nhau của cùng cảnh."""

import pytest
from app.evaluation import metrics_at_k, QueryLabels
from app.labs import pagerank


def test_event_dedup_graded_and_exhaustive_ap():
    """Hai frame của một event chỉ hit một lần; AP chưa exhaustive phải là N/A."""
    events = [{"event_id": "e", "video_uid": "v", "start_ms": 0, "end_ms": 2000, "grade": 2}]
    results = [{"video_uid": "v", "timestamp_ms": 100}, {"video_uid": "v", "timestamp_ms": 200}]
    metrics = metrics_at_k(results, events, 2)
    assert metrics["Recall@2"] == 1 and metrics["Precision@2"] == .5
    assert metrics["nDCG@2"] == 1 and metrics["AP@2"] is None
    assert metrics_at_k(results, events, 2, True)["AP@2"] == 1


def test_overlap_labels_rejected_and_dangling_pagerank():
    """Nhãn overlap gây double gain phải bị từ chối, PageRank không mất mass ở node dangling."""
    with pytest.raises(ValueError):
        QueryLabels(query_id="q", query="x", events=[{"event_id": str(i), "video_uid": "v", "start_ms": 0, "end_ms": 2, "grade": 1} for i in range(2)])
    ranks = pagerank({"A": ["B"], "B": [], "C": ["A"]})
    assert sum(ranks.values()) == pytest.approx(1)
    assert ranks["B"] > ranks["C"]
