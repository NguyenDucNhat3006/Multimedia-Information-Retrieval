"""Ngăn encoder identity đổi theo địa chỉ RAM giữa process pipeline và process API."""

import os
import subprocess
import sys
import importlib.util
import pytest
from app.encoders import preprocessing_fingerprint


def test_hash_removes_callable_address_but_keeps_config_change():
    """repr Compose chứa callable address: cùng transform phải hash bằng nhau ở process khác."""
    class Transform:
        def __init__(self, address):
            self.address = address
        def __repr__(self):
            return f"Compose(<function _convert_to_rgb at {self.address}>)"
    assert preprocessing_fingerprint(Transform("0x123"), {"size": 224}) == preprocessing_fingerprint(Transform("0x456"), {"size": 224})
    assert preprocessing_fingerprint(Transform("0x123"), {"size": 224}) != preprocessing_fingerprint(Transform("0x123"), {"size": 336})


def test_real_transform_hash_same_across_processes_without_weights():
    """Transform thật OpenCLIP có function address; regression chạy hai interpreter, không download weights."""
    if importlib.util.find_spec("open_clip") is None:
        pytest.skip("Core-only không cài OpenCLIP, không khẳng định visual dependency pass")
    code = "from open_clip.transform import image_transform;from app.encoders import preprocessing_fingerprint;t=image_transform(224,is_train=False);print(preprocessing_fingerprint(t,{'size':224}))"
    environment = dict(os.environ, OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
    outputs = [subprocess.check_output([sys.executable, "-c", code], env=environment, text=True).strip() for _ in range(2)]
    assert outputs[0] == outputs[1]
