# Linux tương đương

Đề cương CS336 nêu Python/Linux; code giữ Path/SQLite/PyAV tương thích Windows. Linux commands dưới đây là hướng dẫn, chưa chạy trên Linux trong phiên này.

```bash
cd '/duong/dan/mutimedia-information-retrival'
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test,visual]'
cd frontend
npm ci
npm run build
cd ..
.venv/bin/python -m app.cli doctor
bash scripts/start.sh
```

Server chạy foreground trên 127.0.0.1:8000, Ctrl+C để dừng. requirements-lock.txt là snapshot Windows/CPU; một số package version phụ thuộc nền tảng cần lock lại sau chạy thật Linux, không tuyên bố snapshot Windows là lock Linux đã kiểm chứng. Dùng direct dependency pins trong pyproject.toml làm đầu vào rồi lưu freeze của môi trường Linux riêng. PyAV wheel cung cấp decoder; không cần VM, Docker hay Milvus cho bản nhẹ.

```bash
.venv/bin/python -m app.cli inspect-data '/data/batch2.zip'
.venv/bin/python -m app.cli ingest '/data/video có dấu.mp4' --batch local --interval-ms 2000 --batch-size 8 --download-weights
.venv/bin/python -m pytest -q
```

Chuyển `CS336_DATA_ROOT` bằng `export CS336_DATA_ROOT='/data/runtime'`. Trình duyệt không biết path Linux/Windows; chỉ URL media theo ID. GPU wheel và OCR language data cần cài riêng rồi đo, không dùng kết quả Windows CPU để khẳng định Linux/CUDA pass.
