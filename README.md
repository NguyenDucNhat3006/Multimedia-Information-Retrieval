# CS336 · Truy vấn sự kiện video

Đồ án cho Nguyễn Đức Nhật: Python/FastAPI, React/TypeScript và index vector NumPy chạy Windows native. Pipeline và website sử dụng video local, timestamp PTS trên timeline gốc, embedding OpenCLIP thật. DRES mặc định dry run, không tự liên hệ server thi.

## Chạy ngay trong workspace đã cài

```powershell
Set-Location 'D:\mutimedia-information-retrival'
.\scripts\start.ps1
# Mở http://127.0.0.1:8000
# Khi xong:
.\scripts\stop.ps1
```

Đã lập index smoke cho **2 video thật, 72 keyframe**: `L02_V020` (đầu 94 giây) và `L05_V021` (đầu 46 giây), sample mỗi 2 giây. Đây là tập con để kiểm tra tích hợp, chưa phải toàn batch. Thử truy vấn tiếng Anh `a television news presenter`, bấm một kết quả để xem video tại mốc đã chọn. Chế độ OCR/ASR tự báo chưa có dữ liệu; không sinh transcript giả.

## Cài lại và nhập video

```powershell
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m app.cli doctor
.\.venv\Scripts\python.exe -m app.cli inspect-data 'E:\batch2.zip' 'E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1'
.\.venv\Scripts\python.exe -m app.cli ingest 'E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1\L02_V020.mp4' --batch batch1 --interval-ms 2000 --max-frames 48 --batch-size 8 --download-weights
```

`--download-weights` cho phép tải model có chủ ý; web startup/search không tải model hoặc dataset. Bỏ `--max-frames` mới index cả video; ingest thư mục mặc định giới hạn 3 video, `--limit 0` xử lý tất cả video đã chọn. Dữ liệu runtime, model cache và venv nằm trên D. Không sửa môi trường QLoRA cũ.

## Kiểm tra và học

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests scripts/smoke_real.py
Set-Location frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run build
```

Đọc [giáo trình toàn hệ thống](docs/HUONG_DAN_TOAN_BO_HE_THONG.md), [trạng thái triển khai](docs/IMPLEMENTATION_STATUS.md), [hướng dẫn Windows](docs/SETUP_WINDOWS.md) và [báo cáo smoke thật](docs/reports/smoke-real.json). Kết quả kiểm tra cuối nằm trong [VALIDATION.md](docs/VALIDATION.md).

Mã mới được viết độc lập sau [audit baseline](docs/BASELINE_AUDIT.md); không sao chép repo chưa có LICENSE. Dữ liệu video do người dùng cung cấp, không công khai lại. Luật/profile AIC2024 là tài liệu lịch sử; chưa xác nhận server/luật thi hiện tại. Chưa có nhãn relevance thực, chưa đo Recall/MRR/mAP trên dataset, chưa kiểm tra CUDA, live DRES, OCR/ASR hoặc FAISS trên máy này.
