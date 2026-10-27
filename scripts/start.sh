#!/usr/bin/env bash
# Linux chạy foreground để Ctrl+C dừng đúng process, không yêu cầu Docker/VM.
set -euo pipefail
cd "$(dirname "$0")/.."
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
exec .venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port "${1:-8000}" --workers 1
