# Pipeline dữ liệu offline

Pipeline nằm trong `app/pipeline.py`, được gọi bằng `python -m app.cli`. Website chỉ truy vấn dữ liệu đã chuẩn bị; extraction và embedding chạy trong process CLI riêng. Tất cả lệnh dưới đây chạy tại `D:\mutimedia-information-retrival` bằng Python của `.venv`.

## Khảo sát trước khi decode

```powershell
.venv\Scripts\python.exe -m app.cli doctor
.venv\Scripts\python.exe -m app.cli inspect-data 'E:\batch2.zip' 'E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1' --output data_inventory.json
```

`doctor()` lưu `data/doctor.json`: Python thực tế, package version, số CPU logic, RAM, dung lượng trống trên ổ chứa data, thông tin `nvidia-smi`, ffmpeg/ffprobe binary và trạng thái weights local. PyAV đã bao gồm FFmpeg libraries nên thiếu `ffmpeg.exe` không đồng nghĩa extraction unavailable. Torch đang chạy CPU và thông tin GPU vật lý là hai phép kiểm tra khác nhau.

`inspect_data()` đọc central directory bằng `zipfile.ZipFile(..., allowZip64=True)` hoặc dùng filesystem stat cho thư mục. Nó không decode từng video. Report có compressed/uncompressed bytes, extension, top-level paths, ví dụ và video nhỏ nhất. Nhiều input được CLI so sánh tên video giữa batch. Codec/FPS/duration và ground truth vẫn unknown đến khi kiểm tra chúng. Không giả định file `.npy` có sẵn tương thích OpenCLIP đang dùng.

Khi cần một video từ ZIP local, dùng allowlist cụ thể:

```powershell
.venv\Scripts\python.exe -m app.cli extract-zip 'E:\batch2.zip' 'D:\mutimedia-information-retrival\data\zip-subset' --member 'TEN_MEMBER_QUAN_SAT_DUOC.mp4' --max-bytes 1000000000
```

Thay member bằng đúng tên trong inventory. Lệnh không đoán tên, không extract toàn ZIP, không overwrite. Nó kiểm tra slash/backslash, `..`, absolute path, drive prefix, symlink, tổng byte, dung lượng trống và CRC. Không triển khai remote selective ZIP/Drive downloader trong phiên bản này.

## Video → PTS → ảnh

```powershell
.venv\Scripts\python.exe -m app.cli extract 'E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1\L02_V020.mp4' --batch batch1 --interval-ms 2000 --max-frames 48
```

`extract_video()` probe metadata bằng PyAV rồi decode từ đầu theo thứ tự frame gốc. Mỗi frame có PTS và time base hữu tỷ. Timestamp dùng `round((pts - origin_pts) * time_base * 1000)`, với origin lấy stream start hoặc PTS đầu tiên nếu stream thiếu start. Đây là timeline video gốc bắt đầu tại 0. Video VFR không dùng FPS trung bình để suy thời gian.

Sampling chọn frame đầu tiên đạt mốc tiếp theo; timestamp đã lưu là thời điểm frame thực, không ép thành mốc sampling mong muốn. Chẳng hạn sampling 2000 ms trên stream có frame ở 2002 ms sẽ ghi 2002. `original_frame_index` là vị trí decode từ 0. Keyframe thứ 12 không mặc nhiên là frame gốc thứ 12.

`max_frames` giới hạn smoke subset. Full video duration và media vẫn giữ nguyên, nên seek và DRES point validation dùng đúng video gốc. Không báo subset là đã ingest toàn video. Khi input ở ngoài data root, một bản copy video được đặt vào `data/media/<video_uid>/`; backend chỉ phục vụ media dưới data root bằng ID.

Ảnh full lưu tại `data/frames/<video_uid>/<keyframe_id>.jpg` với quality 95 để encoder/OCR có độ phân giải gốc. Thumbnail riêng tối đa 384×216 lưu dưới `data/thumbnails`. Code không dùng thumbnail UI thay cho preprocessing của OpenCLIP.

VFR trong metadata là dấu hiệu quan sát từ delta PTS của phần đã decode. Giá trị false khi sample có delta cố định không phải bằng chứng đã kiểm tra toàn video CFR. Extraction luôn dùng PTS dù giá trị VFR là gì. Thiếu PTS, duration không hợp lệ hoặc timestamp vượt duration làm job thất bại, không fallback 25 FPS.

## Resume và thay cấu hình

`source_fingerprint()` đọc size, mtime, 1 MiB đầu và 1 MiB cuối. Prefix `sampled-sha256:` công khai rằng đây không phải full-file checksum. Cách này tránh băm cả kho 116 GB trong mỗi lượt resume. Shard và model weights dùng SHA256 toàn file.

Checkpoint extraction dưới `data/checkpoints/extract-<video_uid>.json` chứa fingerprint, pipeline version, interval và max frames. Chạy lại cùng input/cấu hình và đủ ảnh sẽ resume, không thêm bản ghi trùng. UID ổn định trong cùng source path/source batch. Thay source fingerprint hoặc sampling tạo keyframe ID mới; transaction thay toàn bộ keyframes của video và xóa feedback/candidate tham chiếu cũ. Các segment text có thời gian trên video gốc vẫn giữ.

Extraction phải decode lại từ đầu khi chưa có checkpoint hoàn chỉnh; không tuyên bố resume decoder ở PTS giữa file. Embedding resume theo chunk đã commit và checksum. Job `running` còn lại sau process bị kill là bằng chứng interruption; chạy lại CLI dùng checkpoint hợp lệ. Không tự coi job đó là completed.

## Ảnh → embedding

```powershell
.venv\Scripts\python.exe -m app.cli embed --batch-size 8 --download-weights
.venv\Scripts\python.exe -m app.cli index --shard-size 8192
```

`--download-weights` cho phép tải OpenCLIP tường minh. Nếu đã có cache, bỏ cờ này để đảm bảo local-only. Cache nằm trên ổ D tại `data/model-cache`, không dùng mặc định ổ C. Model nhỏ mặc định `ViT-B-32`/`laion2b_s34b_b79k`, device CPU; cấu hình `CS336_DEVICE=auto` dùng CUDA khi Torch CUDA khả dụng, ngược lại CPU. Torch CPU đang cài không thể suy ra GPU inference đã pass.

`OpenClipEncoder.load()` nạp model một lần/process, `eval()`, precision float32 và `torch.inference_mode()`. Text và image dùng cùng model/checkpoint. Preprocessing hash lấy từ transform thực; encoder ID gồm model, checkpoint SHA256, preprocessing hash và dimension đo bằng model. Cùng dimension chưa đủ để hợp nhất hai nguồn vector.

`embed_dataset()` chia batch, đọc full frame, L2-normalize float32 `[batch, dimension]`, lưu `.npy` và mapping JSON có checksum. CUDA OOM giảm batch còn một nửa rồi thử lại cùng offset; chunk chưa ghi thành công không được bỏ qua. CPU vẫn dùng batch nhỏ. JSON `data/embeddings/manifest.json` chỉ publish khi hoàn tất tất cả chunk.

`build_index()` so sánh dataset/keyframe fingerprints với DB hiện tại, model config, encoder ID trên từng keyframe, vector/mapping checksum và tập ID. Thiếu evidence, thiếu mapping hoặc mixed space đều lỗi. Phiên bản hiện tại chưa có lệnh import vector ngoài; vector chưa xác định provenance phải để ngoài index hoặc re-encode.

## Commit index

`publish_index()` tạo `data/index/versions/<version>/`, ghi float32 shard và row→keyframe mapping. `NumpyShardIndex` đọc lại bằng mmap để xác minh schema, dimension, norm, checksum, uniqueness và row count. Chỉ sau khi pass, `os.replace` thay `CURRENT` nguyên tử. Search process đang giữ bản cũ tiếp tục dùng bản bất biến đó; query sau phát hiện CURRENT mới và refresh. Index cũ được giữ để audit/rollback; chưa có lệnh dọn phiên bản tự động.

Exact search chia block 4096 vectors. RAM vector query không cần tải toàn index; mỗi shard mmap. ID mapping vẫn nằm trong RAM nên cần dự toán thêm bộ nhớ khi ingest hàng triệu frame. FAISS CPU là adapter tùy chọn trong `app/index.py`, cần cài dependency riêng, không phải điều kiện để Windows khởi động.

Một lệnh ghép các bước:

```powershell
.venv\Scripts\python.exe -m app.cli ingest 'E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1' --batch batch1 --limit 3 --interval-ms 2000 --max-frames 48 --batch-size 8
```

`--limit 3` là giới hạn mặc định khi truyền thư mục. `--limit 0` xử lý toàn bộ input đã chọn; chỉ dùng sau inventory và dự toán disk. Full frames có thể chiếm nhiều disk hơn thumbnails/embeddings; không suy dung lượng làm việc từ ZIP compressed bytes.

## OCR/ASR

```powershell
.venv\Scripts\python.exe -m app.cli import-text '.\my_ocr.json' --source ocr
.venv\Scripts\python.exe -m app.cli ocr --video-uid '<UID>' --language vie+eng
.venv\Scripts\python.exe -m app.cli asr '<UID>' --model small --language vi
```

Import nhận JSON array, JSONL hoặc CSV: `video_uid,start_ms,end_ms,source,text`. Có thể dùng `media_item_name` chỉ khi tên resolve đúng một video. Toàn batch validate trước transaction, gồm duration và interval. ID content-stable nên import lại không nhân bản.

OCR thực cần `pytesseract`, Tesseract binary và language data `vie`/`eng`; kiểm tra languages trước chạy. Nó dùng full frame và lưu box/confidence tại timestamp frame. ASR thực cần `faster-whisper`; mặc định `local_files_only=True`, CPU int8, model cache riêng trên D. Cờ `--download-weights` cho phép tải khi người dùng thực sự chạy lệnh ASR. Không có dependency/model thì báo lỗi, không sinh text thay thế.

## Fixture và tự kiểm tra

```powershell
.venv\Scripts\python.exe -m app.cli --data-root data-fixture fixture
.venv\Scripts\python.exe -m pytest tests/test_pipeline.py tests/test_retrieval.py -q
```

Fixture là video màu do PyAV tạo với OCR/ASR text khai báo, dùng encoder từ điển màu chỉ để test contract. Data root có video thật sẽ từ chối fixture encoder. Không dùng Recall/MRR trên fixture để kết luận chất lượng HCMAI24. Tests kiểm tra ZIP traversal, PTS/original frame index, resume, sampling invalidation, mapping, normalized vector và atomic publication.

Bài tự kiểm tra: thay `interval_ms` từ 1000 thành 500 rồi chạy `index` mà chưa `embed` sẽ ra sao? Đáp án: keyframe fingerprint và mapping đã đổi; build bị từ chối, CURRENT cũ giữ nguyên. Chạy embed mới rồi index để hoàn tất dữ liệu derived mới.
