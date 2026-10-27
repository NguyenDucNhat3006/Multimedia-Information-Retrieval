# Inventory thực tế · 14/10/2026

Nguồn: [data_inventory.json](../data_inventory.json), [doctor.json](reports/doctor.json), [smoke-real.json](reports/smoke-real.json). ZIP chỉ đọc central directory ZIP64; batch1 chỉ stat filesystem. Không tải Drive, không giải nén toàn bộ ZIP.

| Nguồn đã quan sát | Số file | Loại | Byte nội dung |
|---|---:|---|---:|
| `E:\batch2.zip` | 363 | MP4 | 49,009,010,972 |
| thư mục batch1 người dùng cung cấp | 363 | MP4 | 66,931,802,158 |

ZIP batch2 có archive size 49,009,103,130 bytes, compressed payload bằng uncompressed payload (stored). Tên entry ví dụ `mlcv1/Datasets/HCMAI24/updated/videos/batch2/L24_V024.mp4`. Không thấy sidecar keyframe, vector, map, OCR, ASR hoặc ground truth **trong hai input đã kiểm kê**. Không suy rộng sang thư mục khác chưa đọc. So sánh stem filename toàn hai input không phát hiện trùng media name; backend vẫn chặn submission nếu import về sau tạo xung đột.

Không đọc `bacth1.zip` local vì người dùng đưa thư mục đã giải nén, không đưa archive đó. Kích thước ZIP batch1 trong prompt là thông tin nguồn trước đó, chưa được phiên triển khai này tự xác minh qua Drive.

Smoke đã probe/decode hai video: `L02_V020` duration 913000 ms, `L05_V021` duration 928520 ms. Metadata codec, kích thước, FPS hữu tỷ và time base lưu trong SQLite. Sample 48/24 keyframe mỗi 2000 ms, timestamp nguồn `decoder_pts`, mốc cuối 94000/46000 ms. Không thấy PTS delta thay đổi trong phần decode smoke; chưa chứng minh toàn video đều CFR. Không dùng FPS trung bình để suy timestamp.

Máy Windows 11, Python 3.12.10, 12 logical CPU, RAM 17,009,004,544 bytes, NVIDIA GTX1660Ti 6144 MiB theo nvidia-smi. Torch hiện là bản CPU, GPU tồn tại không đồng nghĩa CUDA đã kiểm tra. PyAV16.0.1 có FFmpeg decoder liên kết trong wheel; không cần ffprobe binary cho path đã chạy. Binary ffmpeg/ffprobe độc lập chưa có.

Dung lượng ổ D lúc doctor xem trong report, thay đổi theo runtime. Cả batch1 đã ở E; nếu copy thêm 66.93 GB vào D có thể thiếu chỗ cho keyframe/vector/model. Trước full ingest, chọn data root trên volume đủ chỗ và chạy doctor. Công thức dự toán: bytes media cần copy + số frame × bytes ảnh full/thumbnail đo từ mẫu + N×D×4 cho vector + mapping/index phiên bản + cache/model/tạm. Không dùng dung lượng ZIP như dung lượng làm việc.

Chưa biết codec/FPS/duration của 724 video còn lại, nhãn relevance, chất lượng truy vấn tiếng Việt, OCR/ASR hay server thi hiện tại. Không công bố Recall hoặc điểm thi từ smoke. `inspect-data` tiếp tục ghi JSON inventory; báo cáo Markdown này là tổng hợp đã kiểm tra của phiên hiện tại.
