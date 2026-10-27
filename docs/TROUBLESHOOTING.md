# Chẩn đoán theo triệu chứng

- Web không kết nối: GET `http://127.0.0.1:8000/api/health`. Nếu không trả `{status:ok}`, đọc `.runtime/server-error.log`; kiểm tra port và chạy scripts/start.ps1 sau build. Không cần giải nén ZIP để health hoạt động.
- Trang trắng: chạy `npm.cmd ci`, `npm.cmd run build` trong frontend; start lại để FastAPI mount dist. Dev riêng: npm run dev, proxy backend port8000.
- Visual unavailable: chạy doctor, extract → embed → index. `embed --download-weights` cho phép tải checkpoint; tìm kiếm không tự tải. Cache ở data/model-cache. Không đổi encoder tag rồi sử dụng index cũ.
- Corrupt shard/missing map: loader từ chối, không tìm ngẫu nhiên. Kiểm tra checksum/manifest và encode/index lại từ frame hợp lệ, không sửa row map bằng tay.
- OCR/ASR unavailable: dataset local chỉ có MP4. Import transcript timestamp-ms hoặc cài dependency + model/ngôn ngữ rồi chạy adapter. Core visual vẫn dùng được.
- Video không phát: kiểm tra URL media theo ID; 404 thiếu file, 403 path nằm ngoài root, 416 range sai. MP4 codec phải được trình duyệt hỗ trợ; bản smoke H.264 đã thử player. Proxy nếu chuyển codec cần giữ timeline gốc, không tự xê dịch timestamp.
- Timestamp sai: xem timestamp_source, PTS/time_base/start_time. Không lấy số thứ tự thumbnail để chia FPS. VFR không dùng FPS trung bình. Không mặc định25FPS để nộp thi.
- Submit409: cùng namespace/evaluation/task/payload đã được reserve. Đối chiếu ledger; không sửa task_key chỉ để vượt chống trùng trong cùng task. Task mới phải dùng task_key thực mới.
- Submit unknown: server có thể đã nhận; đối chiếu lịch sử DRES thủ công, không bấm retry. HTTP200/202 accepted_pending chưa phải correct.
- Live bị chặn: mặc định DRES_DRY_RUN=true. Cần server/luật hiện tại xác nhận, ENV backend và explicit live request; token không vào browser. Không dùng server lịch sử tự động.
- Lỗi Unicode terminal: CLI tự reconfigure UTF-8; scripts Python trực tiếp dùng `python -X utf8`. Đọc JSON PowerShell với `-Encoding UTF8`.
- Out of memory: giảm batch-size, float32/CPU path, một worker. Pipeline giảm batch CUDA OOM; không dùng BF16 mặc định trên GTX1660Ti. Kiểm tra disk doctor trước full ingest, C cache/TEMP đặt D.

Không xóa data/DB của người dùng để chữa lỗi; dùng data root khác cho fixture hoặc thử nghiệm. Chỉ rebuild index sau khi đã bảo toàn media/metadata và xác minh encoder.
