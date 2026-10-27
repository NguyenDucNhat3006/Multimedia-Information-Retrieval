"""Index cosine theo shard: kiểm tra toàn vẹn, mmap và publish nguyên tử.

Vector đã chuẩn hóa L2 nên inner product đúng bằng cosine. File CURRENT là
điểm commit duy nhất; tiến trình đang đọc giữ nguyên phiên bản đã mở.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np


def sha256_file(path: Path) -> str:
    """Băm streaming; không đọc toàn bộ shard/model vào RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(vectors: np.ndarray) -> np.ndarray:
    """Trả float32 [N,D] hoặc [D] chuẩn hóa; từ chối NaN và vector zero."""
    values = np.asarray(vectors, dtype=np.float32)
    if values.ndim not in (1, 2) or not np.isfinite(values).all():
        raise ValueError("Vector phải hữu hạn và có shape [D] hoặc [N,D].")
    lengths = np.linalg.norm(values, axis=-1, keepdims=True)
    if np.any(lengths <= 1e-12):
        raise ValueError("Không thể chuẩn hóa vector zero.")
    return values / lengths


class VectorIndex(Protocol):
    """Hợp đồng index độc lập với NumPy/FAISS; score luôn là cosine."""
    def search(self, query: np.ndarray, top_k: int, allowed_ids: set[str] | None = None) -> list[tuple[str, float]]: ...
    def vector(self, keyframe_id: str) -> np.ndarray: ...


class NumpyShardIndex:
    """Mở index bất biến bằng mmap, xác minh checksum trước khi phục vụ.

    Args: root: thư mục index; expected_encoder_id: space được yêu cầu.
    Raises: ValueError khi manifest, norm, mapping hoặc shard sai.
    """
    def __init__(self, root: Path | str, expected_encoder_id: str | None = None, *, version_override: str | None = None):
        self.root = Path(root)
        pointer = self.root / "CURRENT"
        if version_override is None and not pointer.exists():
            raise FileNotFoundError("Chưa có index được publish; chạy embed và index trước.")
        self.version = version_override or pointer.read_text(encoding="utf-8").strip()
        if not self.version or Path(self.version).name != self.version:
            raise ValueError("CURRENT chứa phiên bản không hợp lệ.")
        self.directory = self.root / "versions" / self.version
        self.manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        if self.manifest.get("schema_version") != 1 or self.manifest.get("normalization") != "l2":
            raise ValueError("Schema/normalization index không được hỗ trợ.")
        if self.manifest.get("version") != self.version or int(self.manifest.get("dimension", 0)) <= 0 or int(self.manifest.get("row_count", 0)) <= 0:
            raise ValueError("Phiên bản/dimension/row_count của manifest không hợp lệ.")
        self.encoder_id = self.manifest["encoder_id"]
        if expected_encoder_id and self.encoder_id != expected_encoder_id:
            raise ValueError("Encoder mismatch: cùng dimension không có nghĩa cùng embedding space.")
        self.dimension = int(self.manifest["dimension"])
        self.shards: list[tuple[list[str], np.ndarray]] = []
        self.locations: dict[str, tuple[int, int]] = {}
        for shard in self.manifest["shards"]:
            for key in ("vectors", "mapping"):
                name = shard[key]
                if Path(name).name != name:
                    raise ValueError("Manifest shard có đường dẫn không an toàn.")
                path = self.directory / name
                if not path.is_file() or sha256_file(path) != shard[f"{key}_sha256"]:
                    raise ValueError(f"Shard hỏng hoặc thiếu mapping: {name}")
            ids = json.loads((self.directory / shard["mapping"]).read_text(encoding="utf-8"))
            values = np.load(self.directory / shard["vectors"], mmap_mode="r", allow_pickle=False)
            if values.dtype != np.float32 or values.shape != (len(ids), self.dimension) or len(ids) != shard["rows"]:
                raise ValueError("Row count/dimension/dtype của shard không khớp manifest.")
            for start in range(0, len(ids), 4096):
                block = values[start:start + 4096]
                if not np.isfinite(block).all() or not np.allclose(np.linalg.norm(block, axis=1), 1, atol=2e-4):
                    raise ValueError("Index chứa vector không hữu hạn hoặc chưa chuẩn hóa L2.")
            shard_number = len(self.shards)
            for position, keyframe_id in enumerate(ids):
                if not isinstance(keyframe_id, str) or keyframe_id in self.locations:
                    raise ValueError("Mapping keyframe phải là chuỗi duy nhất.")
                self.locations[keyframe_id] = shard_number, position
            self.shards.append((ids, values))
        if len(self.locations) != self.manifest["row_count"]:
            raise ValueError("Tổng mapping không khớp row_count.")

    def search(self, query: np.ndarray, top_k: int = 24, allowed_ids: set[str] | None = None) -> list[tuple[str, float]]:
        """Exact search theo block; áp dụng filter trước top-k, RAM O(block*D)."""
        query = normalize(query)
        if query.shape != (self.dimension,):
            raise ValueError("Query dimension không khớp encoder của index.")
        if top_k <= 0:
            return []
        winners: list[tuple[str, float]] = []
        for ids, values in self.shards:
            for start in range(0, len(ids), 4096):
                block_ids = ids[start:start + 4096]
                positions = [i for i, identifier in enumerate(block_ids) if allowed_ids is None or identifier in allowed_ids]
                if not positions:
                    continue
                scores = values[start:start + len(block_ids)][positions] @ query
                count = min(top_k, len(scores))
                selected = np.argpartition(scores, len(scores) - count)[-count:]
                winners.extend((block_ids[positions[int(i)]], float(scores[i])) for i in selected)
                winners = sorted(winners, key=lambda item: (-item[1], item[0]))[:top_k]
        return winners

    def vector(self, keyframe_id: str) -> np.ndarray:
        """Lấy bản sao vector để Rocchio không sửa dữ liệu mmap bất biến."""
        if keyframe_id not in self.locations:
            raise ValueError("Keyframe chưa có trong phiên bản index hiện tại.")
        shard, position = self.locations[keyframe_id]
        return np.array(self.shards[shard][1][position], dtype=np.float32)


def publish_index(root: Path | str, batches: Iterable[tuple[list[str], np.ndarray]], encoder: dict, *, dataset_fingerprint: str, keyframe_fingerprint: str, shard_size: int = 8192) -> dict:
    """Dựng phiên bản mới theo batch rồi commit CURRENT bằng os.replace.

    encoder phải chứa encoder_id, dimension, checkpoint_sha256 và
    preprocessing_hash. Không sửa phiên bản cũ nếu ghi/kiểm tra thất bại.
    """
    if shard_size < 1:
        raise ValueError("shard_size phải dương.")
    for field in ("encoder_id", "dimension", "checkpoint_sha256", "preprocessing_hash"):
        if not encoder.get(field):
            raise ValueError(f"Thiếu bằng chứng encoder: {field}")
    root = Path(root)
    version = uuid.uuid4().hex
    directory = root / "versions" / version
    directory.mkdir(parents=True, exist_ok=False)
    manifest = dict(encoder, schema_version=1, pipeline_version="pts-shards-v1", version=version, dtype="float32", normalization="l2", dataset_fingerprint=dataset_fingerprint, keyframe_fingerprint=keyframe_fingerprint, row_count=0, shards=[])
    seen: set[str] = set()
    for identifiers, values in batches:
        values = normalize(values)
        if values.shape != (len(identifiers), int(encoder["dimension"])):
            raise ValueError("Embedding batch không khớp row mapping/dimension.")
        if len(set(identifiers)) != len(identifiers) or seen.intersection(identifiers):
            raise ValueError("Duplicate keyframe trong mapping.")
        if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
            raise ValueError("Mapping ID phải là chuỗi không rỗng.")
        seen.update(identifiers)
        for offset in range(0, len(identifiers), shard_size):
            number = len(manifest["shards"])
            vector_name, mapping_name = f"vectors-{number:06d}.npy", f"mapping-{number:06d}.json"
            subset = identifiers[offset:offset + shard_size]
            np.save(directory / vector_name, values[offset:offset + shard_size], allow_pickle=False)
            (directory / mapping_name).write_text(json.dumps(subset, ensure_ascii=False), encoding="utf-8")
            manifest["shards"].append({"vectors": vector_name, "mapping": mapping_name, "rows": len(subset), "vectors_sha256": sha256_file(directory / vector_name), "mapping_sha256": sha256_file(directory / mapping_name)})
            manifest["row_count"] += len(subset)
    if not seen:
        raise ValueError("Không publish index rỗng.")
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # Loader production xác minh toàn bộ norm/checksum/mapping trước commit.
    NumpyShardIndex(root, expected_encoder_id=encoder["encoder_id"], version_override=version)
    pointer = root / f".CURRENT-{version}"
    with pointer.open("w", encoding="utf-8") as stream:
        stream.write(version)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pointer, root / "CURRENT")
    return manifest


class FaissIndex:
    """Adapter CPU tùy chọn: vẫn dùng manifest/mapping đã được NumPy kiểm tra."""
    def __init__(self, source: NumpyShardIndex):
        import faiss
        self.source = source
        self.identifiers = [key for ids, _ in source.shards for key in ids]
        self.index = faiss.IndexFlatIP(source.dimension)
        for _, values in source.shards:
            self.index.add(np.asarray(values))

    def search(self, query: np.ndarray, top_k: int = 24, allowed_ids: set[str] | None = None) -> list[tuple[str, float]]:
        """Filter chuyển về exact NumPy để không mất kết quả do post-filter."""
        if allowed_ids is not None:
            return self.source.search(query, top_k, allowed_ids)
        scores, rows = self.index.search(normalize(query)[None, :], min(top_k, len(self.identifiers)))
        return [(self.identifiers[int(row)], float(score)) for row, score in zip(rows[0], scores[0]) if row >= 0]

    def vector(self, keyframe_id: str) -> np.ndarray:
        """Vector luôn thuộc cùng encoder space với source."""
        return self.source.vector(keyframe_id)
