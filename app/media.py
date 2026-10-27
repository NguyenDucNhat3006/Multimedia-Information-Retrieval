"""Truy cập media qua ID: chống traversal/symlink ngoài data root, hỗ trợ seek byte ranges."""

from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse


def safe_path(root: Path, relative_path: str) -> Path:
    """Resolve và kiểm tra file dưới root; đường dẫn tuyệt đối hay symlink ra ngoài bị từ chối."""
    raw = Path(relative_path)
    if raw.is_absolute() or ".." in raw.parts:
        raise HTTPException(403, "Đường dẫn media không hợp lệ")
    path = (root / raw).resolve()
    if not path.is_relative_to(root.resolve()):
        raise HTTPException(403, "Media nằm ngoài data root")
    if not path.is_file():
        raise HTTPException(404, "File media không còn trên máy")
    return path


def media_response(root: Path, relative_path: str) -> FileResponse:
    """FileResponse của Starlette xử lý Range/suffix/416; không trả path vào JSON."""
    return FileResponse(safe_path(root, relative_path), headers={"Cache-Control": "private, max-age=3600"})
