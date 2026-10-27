"""Encoder OpenCLIP nạp lười; không tải weights khi API khởi động.

Mọi vector image/text dùng cùng checkpoint, preprocessing và normalization.
FixtureEncoder chỉ dành cho kiểm tra contract với cảnh màu tự tạo.
"""
from __future__ import annotations

import hashlib
import json
import re
import importlib.metadata
import importlib.util
import os
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

from .index import normalize, sha256_file


class EncoderUnavailable(RuntimeError):
    """Thiếu dependency hoặc weights; API có thể vẫn phục vụ OCR/ASR."""


def preprocessing_fingerprint(preprocess, config: dict) -> str:
    """Hash transform ổn định giữa process; repr callable có địa chỉ RAM phải được loại bỏ.

    Args: preprocess là transform inference thực, config là preprocess_cfg của model.
    Returns: SHA256 của transform/config/version; thay resize/mean/std sẽ invalidate cache.
    """
    stable_repr = re.sub(r" at 0x[0-9a-fA-F]+", "", repr(preprocess))
    versions = {}
    for name in ("open-clip-torch", "torchvision", "Pillow"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    payload = {"transform": stable_repr, "config": config, "versions": versions}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class OpenClipEncoder:
    """OpenCLIP float32 với cache riêng, eval và inference_mode.

    Args: settings: cấu hình model/pretrained/device/data_root.
    allow_download: chỉ CLI embed được bật tải checkpoint một cách tường minh.
    """
    def __init__(self, settings, allow_download: bool = False):
        self.settings = settings
        self.allow_download = allow_download
        self.cache = Path(settings.data_root) / "model-cache"
        self.record_path = self.cache / f"{settings.model_name.replace('/', '_')}--{settings.pretrained.replace('/', '_')}.json"
        self.model = None
        self.metadata: dict = {}

    @property
    def available(self) -> bool:
        """Chỉ kiểm tra file cache; không import Torch hoặc gọi mạng."""
        if any(importlib.util.find_spec(module) is None for module in ("torch", "open_clip")):
            return False
        try:
            record = json.loads(self.record_path.read_text(encoding="utf-8"))
            return Path(record["checkpoint_path"]).is_file()
        except (OSError, KeyError, ValueError):
            return False

    def load(self) -> None:
        """Nạp một lần; checksum làm bất biến identity của embedding space."""
        if self.model is not None:
            return
        try:
            import torch
            import open_clip
        except ImportError as error:
            raise EncoderUnavailable("Cần torch và open_clip_torch; chạy setup môi trường dự án.") from error
        config = open_clip.get_pretrained_cfg(self.settings.model_name, self.settings.pretrained)
        if not config:
            raise EncoderUnavailable("Cặp model/pretrained không có trong OpenCLIP đã cài.")
        record = None
        if self.record_path.exists():
            record = json.loads(self.record_path.read_text(encoding="utf-8"))
        if record and Path(record.get("checkpoint_path", "")).is_file():
            checkpoint = Path(record["checkpoint_path"])
        elif self.allow_download:
            self.cache.mkdir(parents=True, exist_ok=True)
            checkpoint = Path(open_clip.download_pretrained(config, cache_dir=str(self.cache)))
        else:
            raise EncoderUnavailable("Chưa có OpenCLIP weights local. Chạy embed --download-weights; search không tự tải.")
        checkpoint_hash = sha256_file(checkpoint)
        if record and record.get("checkpoint_sha256") != checkpoint_hash:
            raise EncoderUnavailable("Checksum checkpoint cache đã thay đổi; cần re-encode bằng cấu hình đã xác minh.")
        requested = self.settings.device
        device = "cuda" if requested == "auto" and torch.cuda.is_available() else ("cpu" if requested == "auto" else requested)
        if device.startswith("cuda") and not torch.cuda.is_available():
            device = "cpu"
        # Local checkpoint không tự lấy preprocess config từ pretrained tag;
        # truyền cfg tường minh để giữ đúng transform/activation đã dùng training.
        model, _, preprocess = open_clip.create_model_and_transforms(
            self.settings.model_name, pretrained=str(checkpoint), device=device,
            precision="fp32", cache_dir=str(self.cache), pretrained_hf=False,
            force_quick_gelu=bool(config.get("quick_gelu", False)),
            force_image_size=config.get("image_size"), image_mean=config.get("mean"),
            image_std=config.get("std"), image_interpolation=config.get("interpolation"),
            image_resize_mode=config.get("resize_mode"),
        )
        model.eval()
        tokenizer = open_clip.get_tokenizer(self.settings.model_name)
        preprocessing_hash = preprocessing_fingerprint(preprocess, model.visual.preprocess_cfg)
        with torch.inference_mode():
            example = model.encode_text(tokenizer(["dimension probe"]).to(device))
        dimension = int(example.shape[-1])
        identity = json.dumps({"model": self.settings.model_name, "checkpoint_sha256": checkpoint_hash, "preprocessing_hash": preprocessing_hash, "dimension": dimension}, sort_keys=True)
        self.metadata = {"encoder_id": "openclip:" + hashlib.sha256(identity.encode()).hexdigest(), "model_name": self.settings.model_name, "pretrained": self.settings.pretrained, "checkpoint_sha256": checkpoint_hash, "preprocessing_hash": preprocessing_hash, "dimension": dimension, "fixture": False}
        self.cache.mkdir(parents=True, exist_ok=True)
        # Các process inference/pipeline có thể cùng cache: publish record nguyên tử, tránh JSON nửa file.
        temporary = self.record_path.with_name(self.record_path.name + "." + uuid.uuid4().hex + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(dict(self.metadata, checkpoint_path=str(checkpoint.resolve())), stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.record_path)
        self.model, self.preprocess, self.tokenizer, self.device = model, preprocess, tokenizer, device

    def encode_images(self, images: list[Image.Image]) -> np.ndarray:
        """Trả [batch,D] float32 L2; caller chia nhỏ batch khi CUDA OOM."""
        self.load()
        import torch
        with torch.inference_mode():
            tensors = torch.stack([self.preprocess(image.convert("RGB")) for image in images]).to(self.device)
            vectors = self.model.encode_image(tensors).float().cpu().numpy()
        return normalize(vectors)

    def encode_text(self, text: str) -> np.ndarray:
        """Trả [D] cùng space image; không dịch query hoặc gọi API trả phí."""
        self.load()
        import torch
        with torch.inference_mode():
            vectors = self.model.encode_text(self.tokenizer([text]).to(self.device)).float().cpu().numpy()
        return normalize(vectors)[0]


class FixtureEncoder:
    """Encoder cảnh màu fixture, không dùng để tuyên bố semantic benchmark."""
    metadata = {"encoder_id": "fixture-colors-v1", "dimension": 4, "checkpoint_sha256": hashlib.sha256(b"fixture-colors-v1").hexdigest(), "preprocessing_hash": hashlib.sha256(b"mean-rgb-bias-v1").hexdigest(), "fixture": True, "model_name": "fixture-colors", "pretrained": "none"}
    available = True

    def load(self) -> None:
        """Fixture không có model, mạng hoặc checkpoint bên ngoài."""

    def encode_images(self, images: list[Image.Image]) -> np.ndarray:
        """Mean RGB [0,1] và bias: test mapping/cosine trên ảnh tổng hợp."""
        return normalize(np.array([list(np.asarray(image.convert("RGB"), dtype=np.float32).mean(axis=(0, 1)) / 255) + [0.05] for image in images], dtype=np.float32))

    def encode_text(self, text: str) -> np.ndarray:
        """Từ điển màu công khai, chỉ có ý nghĩa với video fixture màu."""
        value = text.casefold()
        colors = [(('red', 'đỏ'), [1, 0, 0, .05]), (('green', 'xanh lá'), [0, 1, 0, .05]), (('blue', 'xanh dương'), [0, 0, 1, .05])]
        for terms, vector in colors:
            if any(term in value for term in terms):
                return normalize(np.array(vector, dtype=np.float32))
        return normalize(np.array([1, 1, 1, .05], dtype=np.float32))


def encoder_for_manifest(settings, manifest: dict | None = None, *, allow_download: bool = False):
    """Chọn fixture chỉ khi manifest tuyên bố rõ; mặc định luôn OpenCLIP."""
    if manifest and manifest.get("fixture"):
        if manifest.get("encoder_id") != FixtureEncoder.metadata["encoder_id"]:
            raise ValueError("Fixture encoder không khớp manifest.")
        return FixtureEncoder()
    return OpenClipEncoder(settings, allow_download=allow_download)
