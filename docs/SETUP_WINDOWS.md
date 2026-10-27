# Windows native

Các lệnh dưới chạy tại `D:\mutimedia-information-retrival`, PowerShell. Python 3.12 được khuyến nghị để dùng wheel đã kiểm tra. Venv riêng không ảnh hưởng QLoRA cũ.

```powershell
Set-Location 'D:\mutimedia-information-retrival'
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m app.cli doctor
.\scripts\start.ps1
```

Setup đọc requirements-lock.txt, npm ci đọc frontend/package-lock.json, build React; expected output có `Setup xong`. Start chạy process ẩn, một worker, in URL/PID; server log ở `.runtime/server-error.log`. Mở `http://127.0.0.1:8000`. Start không tải dữ liệu hoặc checkpoint. Nếu port đang dùng, dùng `start.ps1 -Port 8001`. Stop bằng `scripts/stop.ps1`; script kiểm tra PID/command workspace, không kill process khác.

Không bắt buộc activate venv; gọi executable trực tiếp tránh policy Activate.ps1. Nếu chính script bị policy chặn, mở PowerShell với `-ExecutionPolicy Bypass -File .\scripts\setup.ps1` cho lần chạy này, không đổi policy hệ thống. Đường dẫn có dấu/khoảng trắng đặt trong dấu nháy đơn; Python xử lý Path Unicode.

## Pipeline theo từng bước

```powershell
.\.venv\Scripts\python.exe -m app.cli inspect-data 'E:\batch2.zip' 'E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1' --output data_inventory.json
.\.venv\Scripts\python.exe -m app.cli extract 'E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1\L02_V020.mp4' --batch batch1 --interval-ms 2000 --max-frames 48
.\.venv\Scripts\python.exe -m app.cli embed --batch-size 8 --download-weights
.\.venv\Scripts\python.exe -m app.cli index
```

Expected extract có `timestamp_source` trong DB, `frame_count`, `last_timestamp_ms`; embed có encoder ID và row_count; index có version và checksum. Chạy extract lại cùng cấu hình có `resumed:true`; embed lại có `reused_rows`. CLI dùng stdout UTF-8. Report JSON đọc bằng `Get-Content -Encoding UTF8`.

CPU float32 đã kiểm thử. Lock hiện chứa Torch2.7.0 CPU từ PyPI. `CS336_DEVICE=auto` có CPU fallback, nhưng để dùng GPU phải cài wheel CUDA phù hợp từ [nguồn PyTorch](https://pytorch.org/get-started/previous-versions/) vào **venv dự án**, khóa lại phiên bản và chạy smoke; không ghi GPU pass chỉ vì nvidia-smi có card. BF16 không mặc định. Cache OpenCLIP nằm data/model-cache trên D; không đưa checkpoint vào Git.

```powershell
# Tạo fixture riêng, tuyệt đối không trộn vào dữ liệu thật
.\.venv\Scripts\python.exe -m app.cli --data-root 'D:\mutimedia-information-retrival\data-fixture' fixture
# Dùng data root khác cho server:
$env:CS336_DATA_ROOT='D:\mutimedia-information-retrival\data-fixture'
.\.venv\Scripts\python.exe -m app.cli serve --port 8001
```

Để quay lại dữ liệu thật: `Remove-Item Env:\CS336_DATA_ROOT`. Mọi schema/index tự tạo trong root được chọn. `.env.example` chỉ là mẫu; ứng dụng không tự load file .env. Live DRES vẫn tắt trừ khi backend ENV được cấu hình chủ động.
