"""Bài lab CS336 chạy local: PageRank, phân lớp cosine và k-means trên fixture ghi nhãn."""

import numpy as np


def pagerank(graph: dict[str, list[str]], damping: float = 0.85, iterations: int = 100) -> dict[str, float]:
    """Graph local có directed edges; dangling nodes phân phối đều, không crawl web."""
    nodes = sorted(set(graph) | {n for children in graph.values() for n in children})
    if not nodes:
        return {}
    scores = {n: 1 / len(nodes) for n in nodes}
    for _ in range(iterations):
        dangling = sum(scores[n] for n in nodes if not graph.get(n))
        new = {n: (1 - damping + damping * dangling) / len(nodes) for n in nodes}
        for source in nodes:
            children = graph.get(source, [])
            for target in children:
                new[target] += damping * scores[source] / len(children)
        scores = new
    return scores


def kmeans(vectors: np.ndarray, clusters: int = 2, iterations: int = 30) -> tuple[np.ndarray, np.ndarray]:
    """K-means fixture [N,D] float32, seed cố định và giữ centroid khi cluster rỗng."""
    values = np.asarray(vectors, dtype=np.float32)
    if values.ndim != 2 or not 1 <= clusters <= len(values) or not np.isfinite(values).all():
        raise ValueError("K-means cần N vector hữu hạn và 1<=K<=N")
    centroids = values[np.random.default_rng(42).choice(len(values), clusters, replace=False)].copy()
    labels = np.zeros(len(values), dtype=int)
    for _ in range(iterations):
        labels = ((values[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
        for cluster in range(clusters):
            if np.any(labels == cluster):
                centroids[cluster] = values[labels == cluster].mean(axis=0)
    return labels, centroids


def run_labs() -> dict:
    """Trả output lab minh họa có provenance fixture; không phải benchmark semantic real dataset."""
    from .text_search import TextIndex
    documents = [{"segment_id": "d1", "text": "xe đỏ chạy qua cầu"},
                 {"segment_id": "d2", "text": "xe xanh ở đường"},
                 {"segment_id": "d3", "text": "người đi qua cầu"}]
    index = TextIndex(documents)
    values = np.array([[1, .1], [.95, .05], [.1, 1], [.05, .95]], dtype=np.float32)
    labels, centroids = kmeans(values)
    normalized = values / np.linalg.norm(values, axis=1, keepdims=True)
    prototypes = np.eye(2, dtype=np.float32)
    categories = (normalized @ prototypes.T).argmax(axis=1).tolist()
    return {"provenance": "labelled_fixture", "boolean": index.search('xe AND NOT xanh', method="boolean"),
            "vsm": index.search("xe đỏ", method="tfidf"), "kmeans_labels": labels.tolist(),
            "centroids": centroids.tolist(), "cosine_categories": categories,
            "pagerank": pagerank({"A": ["B", "C"], "B": ["C"], "C": ["A"], "D": []})}
