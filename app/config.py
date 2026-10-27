"""Cấu hình đường dẫn local và model; không chứa mật khẩu hoặc tự tải dữ liệu."""

from dataclasses import dataclass
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    """Một cấu hình bất biến cho mỗi process; mọi đường dẫn được resolve ở server."""

    data_root: Path
    db_path: Path
    index_root: Path
    model_name: str = "ViT-B-32"
    pretrained: str = "laion2b_s34b_b79k"
    device: str = "cpu"
    contest_mode: bool = False
    task_type: str = "textual_kis"

    @classmethod
    def from_env(cls) -> "Settings":
        """Đọc cấu hình CS336_*; không thay đổi môi trường Python khác của người dùng."""
        root = Path(os.environ.get("CS336_DATA_ROOT", str(ROOT / "data"))).resolve()
        return cls(
            data_root=root,
            db_path=Path(os.environ.get("CS336_DB_PATH", str(root / "metadata.sqlite3"))).resolve(),
            index_root=Path(os.environ.get("CS336_INDEX_ROOT", str(root / "index"))).resolve(),
            model_name=os.environ.get("CS336_MODEL_NAME", "ViT-B-32"),
            pretrained=os.environ.get("CS336_PRETRAINED", "laion2b_s34b_b79k"),
            device=os.environ.get("CS336_DEVICE", "cpu"),
            contest_mode=os.environ.get("CS336_CONTEST_MODE", "false").lower() == "true",
            task_type=os.environ.get("CS336_TASK_TYPE", "textual_kis").lower(),
        )

    def ensure_directories(self) -> None:
        """Tạo thư mục runtime, không ghi vào thư mục video input."""
        for path in (self.data_root, self.db_path.parent, self.index_root):
            path.mkdir(parents=True, exist_ok=True)
