# Giáo trình đọc và bảo vệ hệ thống — Nguyễn Đức Nhật

Tài liệu này hướng dẫn đọc code đã hiện thực trong workspace, từ dữ liệu đầu vào đến tìm kiếm, xem video và nộp đáp án. Đọc `README.md` để chạy ứng dụng trước, sau đó học theo từng phần dưới đây. Hai tài liệu hướng dẫn và prompt gốc vẫn được giữ như đầu vào thiết kế. Hệ thống không yêu cầu fine-tune model hoặc gọi API trả phí.

Mục tiêu khi bảo vệ là giải thích được một kết quả: nó đến từ video nào, timestamp được xác định bằng gì, kênh nào đưa nó vào danh sách, điểm số có ý nghĩa gì và vì sao payload DRES hợp lệ. Chạy được giao diện là bước đầu; hiểu và kiểm tra luồng dữ liệu mới giúp phát hiện lỗi.

## 1. Bài toán và dữ liệu đầu vào

Một truy vấn video cần trả **video nào, ở thời điểm nào**. Ví dụ, câu “một người đi xe đạp qua cầu” cần dẫn người dùng đến một khung hình và mốc phát cụ thể. Hệ thống không thay tác vụ này bằng một câu trả lời chung về nội dung video.

Đọc `app/pipeline.py::inspect_data()` và nhánh `inspect-data` trong `app/cli.py::main()`. Input là đường dẫn ZIP hoặc thư mục local. Output là inventory JSON: số file, extension, byte nén và giải nén, các đường dẫn cấp đầu, ví dụ, video nhỏ nhất và các thông tin còn chưa biết. ZIP được đọc qua central directory với ZIP64; bước này không decode mọi video.

```powershell
.venv\Scripts\python.exe -m app.cli inspect-data 'E:\batch2.zip' 'E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1' --output data_inventory.json
```

Inventory đã quan sát hai nguồn chứa tổng cộng 726 video. Integration hiện chọn 2 video, 72 keyframe từ các đoạn đầu; đó là subset, không phải index toàn kho. Video gốc vẫn đầy đủ để phát. Một cảnh chưa được sampling có thể xem trực tiếp nhưng chưa có vector đại diện để tìm thấy.

Ví dụ, central directory của `batch2.zip` liệt kê 363 MP4. Điều này xác nhận nội dung archive đã quan sát; nó không chứng minh rằng một thư mục khác chắc chắn có hoặc không có OCR, ASR hay ground truth. Các nguồn và số đo được lưu trong `docs/DATA_REPORT.md` và report runtime.

Lỗi thường gặp là dùng URL thư mục Drive như một filesystem path, hoặc tải toàn bộ ZIP khi chỉ muốn mở website. Drive là nguồn lấy dữ liệu, còn decoder cần file local đọc được. `inspect-data` và khởi động API không tự tải dataset.

**Tự kiểm tra:** Vì sao inventory phải đi trước extraction?  
**Đáp án:** Inventory giúp chọn subset, dự toán disk, phát hiện trùng tên và biết dữ liệu nào thực sự có. Nếu bỏ bước này, ta dễ giả định transcript, vector hoặc model đã có rồi thiết kế sai pipeline.

Bạn đã hiểu giới hạn đầu vào. Phần tiếp theo xác định ID và đơn vị thời gian để một kết quả luôn trỏ đúng video gốc.

## 2. Schema, ID và timestamp

Đọc `app/schemas.py::Video`, `Keyframe`, `TextSegment`, `EmbeddingManifest` và `app/db.py::Database`. Schema là hợp đồng giữa pipeline, API, retrieval và DRES. SQLite lưu metadata; các thao tác validate/transaction bảo đảm dữ liệu không được ghi thành nửa batch khi một row lỗi.

`video_uid` là ID nội bộ. Pipeline tạo nó từ source path và source batch. `media_item_name` là tên file bỏ extension, dùng khi gửi DRES. Hai field khác mục đích: không tự thêm batch vào media name để tránh trùng tên nếu BTC không dùng tên đó. Tên media trùng vẫn có thể lưu trong DB, nhưng submission phải bị chặn đến khi mapping được xác nhận.

`keyframe_id` phụ thuộc video, timestamp và sampling config. `original_frame_index` là thứ tự frame gốc decoder đếm từ 0, còn `timestamp_ms` là thời điểm trên timeline video gốc. Keyframe thứ 12 không nhất thiết là frame gốc thứ 12.

Mọi field thời gian nghiệp vụ trong API/database dùng integer milliseconds. Schema từ chối bool, string và float cho các trường milliseconds strict. Metadata `start_time` là ngoại lệ có tên và ý nghĩa riêng, theo giây của stream; extraction dùng nó để giải thích origin PTS.

Đọc `app/pipeline.py::pts_timestamp_ms()`:

```text
timestamp_ms = round((PTS - origin_PTS) × time_base × 1000)
```

PTS là timestamp trình bày của frame; time base là một số hữu tỷ. Với VFR, thời gian phải đến từ PTS, không suy từ FPS trung bình. Với CFR đã xác nhận, `cfr_timestamp_ms(300, 25, 1, confirmed_cfr=True)` trả 12000 ms. Với FPS 30000/1001, hàm giữ `Fraction` và trả 10010 ms cho frame gốc 300. Không tự mặc định 25 FPS khi metadata thiếu.

**Input/output nhỏ:** `pts_timestamp_ms(180000, Fraction(1, 90000), 0)` → `2000`. Frontend phát tại 2 giây; payload DRES vẫn dùng 2000 ms.

Lỗi thường gặp là lấy ordinal của ảnh đại diện làm frame index hoặc đổi milliseconds thành seconds trước khi nộp. Cả hai có thể tạo một vị trí hợp lệ về kiểu dữ liệu nhưng sai nội dung.

**Tự kiểm tra:** Một ảnh thứ 3 được lấy bằng sampling 1 giây có chắc ở 3000 ms không?  
**Đáp án:** Không. Nếu đếm ordinal từ 0, ảnh thứ 3 thường gần 2000 ms; decoder còn có thể trả frame ở mốc lệch grid. Phải dùng `timestamp_ms` đã ghi cùng ảnh, không tính lại từ ordinal.

Bạn đã hiểu ID và timeline. Tiếp theo là cách tạo keyframe và giữ cache nhất quán.

## 3. Trích frame, checkpoint và resume

Luồng code là `app/cli.py::main()` → `app/pipeline.py::extract_video()` → `probe_video()` và PyAV decoder. Input là video local, source batch, `interval_ms` và `max_frames` tùy chọn. Output gồm UID, số frame, duration gốc, timestamp cuối, config hash và trạng thái `resumed`.

```powershell
.venv\Scripts\python.exe -m app.cli extract 'E:\mlcv1\Datasets\HCMAI24\updated\videos\batch1\L02_V020.mp4' --batch batch1 --interval-ms 2000 --max-frames 48
```

Pipeline chạy offline trong process CLI riêng. Nó copy input ngoài data root vào media root để backend chỉ phục vụ đường dẫn đã đăng ký. Decoder lấy frame đầu tiên đạt mốc sampling tiếp theo và lưu timestamp PTS thực. Nó lưu ảnh full cho encoder/OCR, thumbnail nhỏ riêng cho website.

Trong smoke thật, 48 frame của `L02_V020` được sampling cách 2 giây, mốc cuối 94000 ms, trong khi duration video gốc là 913000 ms. Giới hạn 48 frame không cắt video thành 94 giây và không đổi duration gửi DRES. Nó chỉ giới hạn phần đã có vector.

Checkpoint extraction chứa pipeline version, source fingerprint, interval và max frames. Chạy lại cùng input/config kiểm tra row count cùng file ảnh đã lưu rồi trả `resumed=true`. Thay sampling hoặc source fingerprint tạo keyframe ID mới và thay metadata derived của video trong transaction; feedback/candidate tham chiếu frame cũ được xóa. Embedding và index cần được xây lại cho mapping mới.

Source fingerprint đọc size, mtime, tối đa 1 MiB đầu và 1 MiB cuối. Prefix `sampled-sha256:` công khai rằng đó là băm lấy mẫu, không phải full-file SHA256. Checksum model weights và vector shards vẫn dùng SHA256 toàn file. Cách này giảm I/O khi resume kho lớn, nhưng không thay thế một full checksum của nguồn dữ liệu.

Nếu process bị kill, job có thể còn `running`; nếu exception được xử lý, job là `failed` và có error. Resume dựa vào checkpoint/chunk đã commit. Extraction chưa hoàn tất phải decode lại từ đầu; chưa có resume decoder từ giữa video. Lỗi thiếu PTS hoặc duration không hợp lệ dừng job, không đoán FPS để tiếp tục.

**Tự kiểm tra:** Vì sao cần giữ full frame dù đã có thumbnail?  
**Đáp án:** Thumbnail giảm băng thông giao diện. Encoder có preprocessing riêng, còn OCR có thể cần chữ ở độ phân giải gốc; dùng thumbnail thay thế có thể làm mất thông tin cần tìm.

Bạn đã hiểu extraction và resume. Tiếp theo là embedding space và commit index.

## 4. Encoder, cosine và index

Đọc `app/encoders.py::OpenClipEncoder.load()`, `encode_images()`, `encode_text()`, sau đó `app/pipeline.py::embed_dataset()`, `build_index()` và `app/index.py::publish_index()`, `NumpyShardIndex`.

Integration hiện dùng OpenCLIP `ViT-B-32`/`laion2b_s34b_b79k`, CPU float32, dimension thực 512. Đây là cấu hình đã chạy; GPU/CUDA không được mặc nhiên coi là đã kiểm tra chỉ vì máy có GPU. Encoder dùng `eval()` và `torch.inference_mode()`, nạp một lần trong mỗi process khi cần inference.

Input image là list ảnh full; output là float32 `[batch, dimension]`. Input text là câu mô tả; output là float32 `[dimension]`. Hai phía dùng cùng checkpoint, transform và space. Mỗi vector được chuẩn hóa L2:

```text
normalize(x) = x / ||x||₂
cosine(x, y) = x · y khi ||x||₂ = ||y||₂ = 1
```

Hàm `normalize()` từ chối zero vector và NaN. Score cosine là độ gần trong embedding space, không phải xác suất cảnh đúng. Không softmax top-k rồi đặt nhãn confidence.

`OpenClipEncoder` không tải weights khi API startup hoặc search thiếu cache. CLI `embed --download-weights` mới cho phép download tường minh, vào `data/model-cache`. Khi nạp checkpoint local, encoder truyền preprocessing config của pretrained tag và kiểm tra checksum để giữ identity đúng.

Manifest ghi model name, checkpoint SHA256, preprocessing hash, dimension, normalization, dtype, dataset/keyframe fingerprints và row mapping. Vector 512 chiều từ một model khác không được ghép chỉ vì shape giống nhau: trục không gian và ý nghĩa tọa độ có thể khác.

`NumpyShardIndex` mmap các shard float32, tính inner product theo block 4096 rows và áp filter trước top-k. Mapping ID vẫn cần RAM; không tải toàn bộ vector matrix vào RAM. `publish_index()` ghi phiên bản mới vào staging, dùng loader kiểm tra norm/checksum/mapping/row count rồi `os.replace` file `CURRENT` nguyên tử. Search giữ một phiên bản bất biến; nó không đọc nửa index cũ, nửa index mới.

FAISS CPU có adapter tùy chọn, nhưng không là điều kiện khởi động trên Windows và chưa được xem là runtime đã pass trong phiên này. Vector import bên ngoài chưa có workflow được kiểm chứng; nguồn thiếu provenance phải để ngoài index hoặc re-encode.

**Tự kiểm tra:** Vì sao một lỗi mapping có thể nguy hiểm hơn lỗi thứ hạng?  
**Đáp án:** Vector gần đúng nhưng row trỏ sai keyframe sẽ trả video/timestamp sai. Người dùng có thể nộp sai dù score cao. Vì vậy checksum, row count, uniqueness và tập ID là invariant bắt buộc.

Bạn đã hiểu embedding/index. Tiếp theo đọc một request Search đi qua toàn bộ hệ thống.

## 5. Từ nút Search đến response

Luồng thực là `frontend/src/App.tsx` → `frontend/src/api.ts` → endpoint `search()` bên trong `app/main.py::create_app()` → `SearchRequest` → `RetrievalService.search()`/`_visual()` → `OpenClipEncoder.encode_text()` → `NumpyShardIndex.search()` → `_result()` → result grid.

Input nhỏ:

```json
{"mode":"visual_text","query":"people outdoors","top_k":8}
```

Response có `query_id`, `index_version`, `elapsed_ms`, `warnings` và `results`. Mỗi result có keyframe ID, video UID, media name, timestamp ms, thumbnail/video URL, score và contributions. URL được resolve qua ID, không chứa absolute filesystem path trên ổ E hoặc D.

`SearchRequest` validate top-k, interval, gap và weights trước inference. `_visual()` kiểm tra encoder ID của query đúng với index, tìm top candidates rồi resolve metadata. Truy vấn không filter chỉ đọc metadata của candidates. Khi filter video/time, tập ID hợp lệ được áp trước top-k; post-filter một danh sách top-k quá nhỏ có thể bỏ hết kết quả hợp lệ.

Hàm `remember()` trong `app/main.py` tạo query ID và lưu request, result count, elapsed time cùng index version vào SQLite. Nó không lưu bytes ảnh upload hay secret DRES. Frontend dùng `AbortController` hủy request cũ; response chậm của query trước không được ghi đè kết quả query mới.

Query tiếng Việt không mặc nhiên đạt chất lượng tiếng Anh với encoder này. `visual_query` cho phép nhập mô tả tiếng Anh riêng cho visual, trong khi `query` gốc phục vụ OCR/ASR. Không có translator tự sinh bản dịch hoặc gọi API trả phí.

Lỗi 503 khi thiếu weights/index có nghĩa visual chưa khả dụng; cần chuẩn bị pipeline hoặc chọn channel đang có dữ liệu. Website hiển thị lỗi/empty/loading theo response thật, không tạo result thay thế.

**Tự kiểm tra:** Thay CSS của result grid có cần embed lại không?  
**Đáp án:** Không. Thay encoder, preprocessing, frame nguồn hoặc sampling mới ảnh hưởng cache/space; bố cục hiển thị không thay vector.

Bạn đã đọc luồng request đến result. Phần tiếp theo nối truy vấn text với các mô hình IR trong môn học.

## 6. Boolean, term, VSM và OCR/ASR

Đọc `app/text_search.py::tokenize()`, `BooleanParser`, `TextIndex` và `search_database()`. Tokenizer dùng NFC + casefold, giữ dấu tiếng Việt và lấy token Unicode. Phiên bản hiện tại chưa stemming hoặc tách từ ghép tiếng Việt; “xe máy” vẫn là hai token.

Grammar có precedence `NOT > AND > OR`, hỗ trợ parentheses và phrase trong dấu ngoặc kép. Operators viết hoa. Term liền nhau ngầm `AND`. Parser dùng recursive descent, không `eval`, không đưa raw query vào SQL. Input `"xe đỏ" AND NOT dừng` đòi phrase liền nhau và loại document chứa “dừng”. Ngoặc hoặc operator thiếu operand sẽ trả lỗi có giải thích.

`TextIndex` dùng posting `term → set(document_id)` để minh họa inverted index/SPIMI nhỏ. Chế độ `method='tfidf'` tính:

```text
tf(t,d) = 1 + ln(count(t,d))
idf(t) = ln((1+N)/(1+df(t))) + 1
score = cosine(vector_query, vector_document)
```

Production `search_database()` dùng Boolean AST để lọc tập segment và SQLite FTS5 BM25 để rank. BM25 và TF-IDF khác cách weighting, không có cùng thang raw score. FTS `unicode61 remove_diacritics 0` giữ dấu, nên “xe” và “xé” không tự đồng nhất. Text gốc được giữ để hiển thị evidence.

OCR/ASR import đi qua `app/pipeline.py::import_text()`. Input là JSON array, JSONL hoặc CSV có `video_uid,start_ms,end_ms,source,text`; output báo số row đã import. Nó validate interval/duration và resolve video trước transaction. ID content-stable giúp import lại không thêm bản sao. Nếu media name resolve nhiều video, cần UID tường minh.

`run_ocr()` là adapter Tesseract thực trên full frame, cần binary và language data `vie+eng`; output lưu text, box/confidence và timestamp frame. `run_asr()` là adapter faster-whisper thực, mặc định chỉ dùng model local; download cần cờ tường minh. Dependency/model chưa có thì báo unavailable. OCR/ASR thật chưa chạy trong integration hiện tại; text fixture là nội dung màu được khai báo, không được gọi là transcript trích từ dataset thật.

**Input/output nhỏ:** segment ASR `[0,2000]` trong video `v1` có thể map các frame của `v1` nằm trong khoảng đó. `_text()` không gán câu này cho frame ở 50000 ms. Nếu interval không chứa frame, chỉ chọn frame gần biên nhất khi cách không quá 1000 ms và còn thỏa time filter.

**Tự kiểm tra:** Boolean search và BM25 có thay thế nhau không?  
**Đáp án:** Trong implementation này, Boolean xác định segment nào được phép xuất hiện; BM25 xếp hạng những segment đó. Query chỉ có NOT có thể trả candidates với score 0 vì không có positive term để rank.

Bạn đã hiểu text IR và mapping segment. Tiếp theo là fusion và chuỗi sự kiện.

## 7. Hybrid, temporal và diversity

Đọc `app/retrieval.py::weighted_rrf()`, `temporal_pairs()` và `RetrievalService._channels()`. Hybrid nhận candidate lists visual/OCR/ASR rồi hợp nhất trên keyframe ID:

```text
RRF(frame) = Σ weight(channel) / (60 + rank(channel, frame))
```

Cosine và BM25 không được cộng raw scores vì khác đơn vị/phân phối. Contributions ghi rank, raw score và phần RRF của từng nguồn. Thiếu OCR/ASR thì hybrid dùng các channel đang có; capabilities/warnings giải thích phần unavailable. Nó không tạo transcript giả để lấp kênh thiếu.

Ví dụ một frame đứng thứ 2 visual và thứ 1 OCR, weights tương ứng 1 và 2, có RRF `1/62 + 2/61`. Raw BM25 rất lớn không thể áp đảo chỉ do thang đo. RRF là điểm rank, không confidence.

Temporal tìm A/B độc lập và fusion từng sự kiện. Candidate B được nhóm theo video, sắp timestamp rồi dùng binary search tìm khoảng gap. Cặp hợp lệ khi cùng video và:

```text
max(1, min_gap_ms) <= B.timestamp_ms - A.timestamp_ms <= max_gap_ms
```

B luôn phải sau A, kể cả khi `min_gap_ms=0`. Với A ở 1000 ms và B ở 4000 ms, gap là 3000 ms; cặp hợp lệ nếu max gap là 3000. B ở video khác hoặc B trước A bị loại. Response giữ keyframe/timestamp B và gap để website có thể xem cả hai điểm.

Implementation chỉ ghép bounded candidates, không tạo ma trận NxN toàn kho. Vì vậy một event tốt ngoài candidate pool có thể bị bỏ; semantic relevance và candidate recall vẫn cần đánh giá trên nhãn thật. Score cao cùng thứ tự hợp lệ không chứng minh nội dung hai event đúng truy vấn.

`group_by_video=true` giữ result tốt nhất mỗi video để xem đa dạng hơn. Đây là tùy chọn phải ghi trong cấu hình benchmark. Khi tắt, không âm thầm đổi danh sách bằng grouping; nhiều frame gần nhau cũng không được mặc nhiên tính là nhiều relevant event.

**Tự kiểm tra:** Temporal đảm bảo điều gì và chưa đảm bảo điều gì?  
**Đáp án:** Nó đảm bảo same video, thứ tự A trước B và gap theo ms trong candidate mapping. Nó chưa chứng minh cảnh thực sự đúng mô tả; người xem hoặc bộ nhãn relevance phải kiểm tra điều đó.

Bạn đã hiểu fusion và temporal. Phần tiếp theo đưa kết quả vào video player và feedback.

## 8. Player, filmstrip, feedback và ứng viên

Đọc `frontend/src/Inspector.tsx`, endpoint `neighbors()`/`feedback()` trong `app/main.py`, và `app/media.py`. `Inspector` nhận selected result; effect chờ `loadedmetadata` rồi gán `video.currentTime = selected.timestamp_ms / 1000`. UI hiển thị milliseconds, còn HTML video nhận seconds. Khi đổi video/mốc, listener và request filmstrip cũ được cleanup.

Input nhỏ `timestamp_ms=12340` phải seek tới 12.34 giây. Filmstrip gọi `/api/videos/<uid>/neighbors?timestamp_ms=12340`, chỉ lấy các frame lân cận của video đó. Chọn frame trước/sau đổi selected result rồi dùng cùng quy tắc seek.

Media route resolve ID → relative path trong DB → `safe_path()`. Nó không nhận filesystem path từ client, ngăn traversal/symlink thoát data root. `FileResponse` hỗ trợ byte ranges để browser seek, gồm suffix ranges và phản hồi 416 cho phạm vi không thỏa mãn. Codec browser không hỗ trợ là lỗi media khác với lỗi search; UI hiển thị thông báo để kiểm tra nguồn.

Feedback POST lưu `(session_id,keyframe_id,relevant)` trong SQLite. Khi bật `use_feedback`, `_visual()` dùng Rocchio trong cùng index space:

```text
q' = normalize(q + 0.75 × mean(relevant_vectors)
                 - 0.25 × mean(irrelevant_vectors))
```

`index.vector()` trả bản sao, nên cập nhật query không sửa mmap. Reset xóa feedback của session. UI tạo session mới khi mở trang mới; nó không giả rằng feedback phiên cũ đang áp dụng. Candidates lưu ID/note độc lập trong DB nên reload vẫn xem lại được.

**Tự kiểm tra:** Feedback có phải fine-tuning model không?  
**Đáp án:** Không. Rocchio thay query vector ở lúc tìm kiếm; checkpoint và vectors trong index giữ nguyên. Fine-tuning sẽ thay model weights và đòi protocol training/validation khác.

Bạn đã hiểu tương tác với kết quả. Tiếp theo chuẩn bị payload DRES có thể review trước khi gửi.

## 9. Preview, submit và submission ledger

Luồng thực là `frontend/src/SubmissionPanel.tsx` → API preview → `app/dres.py::DresService.preview()` → JSON payload. Nút submit là thao tác riêng: `DresService.submit()` → reservation transaction → transport/mock → cập nhật ledger. Backend resolve media name từ keyframe, kiểm tra timestamp không vượt duration và chặn media name mơ hồ.

Profile mặc định là `aic2024_v2` theo DOCX đã cung cấp. Tài liệu 2024 không chứng minh server/luật thi hiện tại giống hệt. Live adapter tắt mặc định, không có host/token thi thật hardcode trong repo. Secret ở server, không đưa vào frontend bundle, localStorage hay URL trang.

KIS point ở 1000 ms tạo payload:

```json
{"answerSets":[{"answers":[{"mediaItemName":"VIDEO_1","start":1000,"end":1000}]}]}
```

QA với answer chuỗi `007` tạo text `007-VIDEO_1-1000`. Không parse answer qua integer làm mất số 0 đầu, không thêm `QA-`, không gửi câu hỏi thay đáp án. Validator profile chỉ chấp nhận ASCII digits `0`–`9`. Evaluation phải chọn explicit; `task_key` không được thay bằng evaluation ID vì một evaluation có thể chứa nhiều task.

Ledger có unique key theo namespace, evaluation, task và payload hash. Reservation xảy ra nguyên tử trước network để double click/đa tab không gửi hai lần. Cùng payload trong task mới có thể được gửi lại. Duplicate trong cùng task báo 409.

Timeout submit tạo trạng thái `unknown`: server có thể đã nhận request, nên không retry POST tự động. HTTP 200 hoặc `status=true` chỉ dẫn đến accepted/pending theo schema, không được tự coi là đáp án correct. Dry run không network và không khóa live namespace; mock có namespace, clock và nhãn local riêng. Xem snapshot/schema hash và chi tiết profile tại `docs/DRES_INTEGRATION.md`.

**Tự kiểm tra:** Vì sao `unknown` khác `rejected`?  
**Đáp án:** Rejected có bằng chứng server từ chối; unknown thiếu kết quả xác nhận. Retry một unknown có thể tạo submission trùng hoặc bị phạt nếu request trước đã được nhận, nên phải đối chiếu lịch sử trước.

Bạn đã hiểu payload và ledger. Tiếp theo phân biệt điểm thi tương tác với chất lượng retrieval offline.

## 10. Điểm luyện tập và đánh giá offline

Đọc `app/dres.py::practice_score()` và `app/evaluation.py::evaluate_file()`, `metrics_at_k()`. Hai phép đo giải quyết hai bài toán khác nhau: mock score đo tiến độ tìm đáp án trong thời gian task; offline metrics đo ranking trên bộ query/relevance được gán nhãn.

Công thức luyện tập theo tài liệu 2024:

```text
score = max(0, 50 + 50 × (1 - t/tL) - 10 × wrong_submissions)
```

Chỉ áp dụng khi đã tìm đúng trong thời hạn; không tìm đúng thì 0. `tL=300` giây cho Textual KIS/QA và 240 giây cho Video KIS. `t` là thời gian từ khi task bắt đầu đến đáp án đúng đầu tiên, khác timestamp trong video. Đúng ngay sau 7 lần sai được 30; clamp đặt ngoài cả biểu thức, không clamp riêng phần accuracy. Mock ground truth do người dùng khai báo, không suy từ result hạng 1.

Offline labels phải có query, event ID, video UID, interval ms và grade. `evaluate_file()` nhận file JSON đã validate, chạy retrieval thật, lưu result từng query, label hash, index version, hardware và latency. `human_reviewed` và `labelled_fixture` là hai provenance khác nhau; không dùng nhãn fixture để khẳng định chất lượng dataset thật.

`metrics_at_k()` tính Recall ở mức event: nhiều frame hit cùng event chỉ tăng recall một lần. Precision@K có mẫu số K, slot thiếu result là không relevant. RR là reciprocal rank của hit đầu; MRR là trung bình RR trên queries. nDCG dùng graded gain `2^grade-1`. AP/mAP@K chỉ công bố khi `exhaustive_judgments=true`; nhãn không đủ thì giá trị là null/N/A.

Ví dụ một relevant event `[1000,3000]` có hai result tại 1500 và 2500 ms: đó vẫn chỉ là một event được tìm thấy. Với K=2 và chỉ event này relevant, Recall@2=1, Precision@2=1/2. Quy tắc này tránh thưởng cho nhiều frame gần nhau của cùng cảnh.

Latency report tách `cold_first` và warm p50/p95 của các query sau. Số mẫu nhỏ chưa đại diện toàn kho. Chưa có nhãn thật thì chuẩn bị label tool/schema và báo chưa benchmark; không tạo Recall/MRR giả. Tune weights trên dev, sau đó chốt cấu hình trước khi đo test.

**Tự kiểm tra:** Unit tests pass có chứng minh Recall cao không?  
**Đáp án:** Không. Tests chứng minh contract, mapping và invariant thuật toán trên input biết đáp án. Chất lượng semantic cần query/ground truth thật, protocol rõ ràng và error analysis.

Bạn đã phân biệt các lớp đánh giá. Tiếp theo nối implementation với những bài lab còn lại của CS336.

## 11. Lab và liên hệ đề cương

Chạy `.venv\Scripts\python.exe -m app.cli lab`, đọc `app/labs.py::run_labs()`, `pagerank()`, `kmeans()` và `docs/COURSE_MAPPING.md`. Output có provenance fixture rõ ràng, giúp học nguyên lý trước khi mở rộng thí nghiệm.

Boolean/VSM lab dùng corpus text nhỏ để thấy tập candidate và weighting. Posting dictionary minh họa inverted index. Categorization dùng cosine với prototype; k-means dùng vectors hai chiều fixture để quan sát việc gán cụm và cập nhật centroid. Đây chưa phải benchmark phân lớp/clustering trên video thật.

PageRank chạy graph local. Dangling node được phân phối đều, damping factor giữ random jump. Video dataset không mặc nhiên có hyperlink graph, nên không tự cộng PageRank vào search score khi chưa có graph/evidence phù hợp. Không cần crawl web rộng chỉ để đủ một chương.

BSBI được giải thích bằng sort từng block rồi merge; SPIMI dùng dictionary/postings và flush block khi cần. Pipeline chunk/shard có liên hệ về việc giới hạn RAM, nhưng code local không được gọi là hệ thống MapReduce phân tán. Phân biệt **đã cài ở core**, **lab chạy được** và **nội dung giải thích** trong course mapping.

**Tự kiểm tra:** Vì sao không tự dùng PageRank để làm mọi result video “chính xác hơn”?  
**Đáp án:** PageRank đo cấu trúc liên kết của graph được định nghĩa. Khi video chưa có graph liên kết hợp lệ, điểm đó không có bằng chứng liên hệ với relevance của query. Lab giúp học thuật toán, còn áp dụng vào ranking cần giả thuyết và đánh giá riêng.

Bạn đã hiểu mapping chương và giới hạn của lab. Phần cuối tập bảo vệ toàn bộ luồng bằng một ví dụ cụ thể.

## 12. Bài tổng hợp: giải thích một kết quả từ đầu đến cuối

Tự vẽ luồng sau và ghi input/output, đơn vị cùng file/hàm cạnh mỗi mũi tên:

```text
Search → request → validate → encode → index → fusion → response
       → grid → chọn frame → seek → preview DRES → submit → ledger
```

Với query visual “people outdoors”, hãy giải thích `SearchRequest` nhận gì, OpenCLIP trả shape nào, index dùng metric nào và kết quả map đến video/timestamp bằng gì. Nếu chuyển sang hybrid, hãy chỉ ra channel nào thật sự khả dụng và công thức fusion. Khi chọn result, chứng minh player dùng milliseconds/1000 đúng tại ranh giới HTML video.

Tiếp theo preview một KIS payload, kiểm tra media name/duration và chỉ ra nơi reservation được tạo trước submit. Thử mock/dry run để minh họa lịch sử mà không gọi server thi thật. Giải thích vì sao response accepted chưa chắc correct và vì sao timeout phải giữ unknown.

**Lời giải mẫu:** React gửi query và cấu hình qua `api.ts`. Pydantic validate; `RetrievalService` encode query trong cùng checkpoint/space với index. Exact search trả ID/cosine, OCR/ASR trả ID/BM25, weighted RRF hợp nhất theo rank nếu chọn hybrid. Backend resolve video UID, media name, timestamp và URL qua ID. `Inspector` seek bằng timestamp ms chia 1000. `SubmissionPanel` gọi preview JSON ms để người dùng review; submit tạo reservation trong ledger rồi mới gọi transport, giữ unknown khi không xác nhận được network outcome.

**Tự kiểm tra:** Hãy nêu bốn điều không thể suy ra chỉ từ một ảnh chụp result grid.  
**Đáp án:** Không thể suy Recall toàn kho, độ chính xác semantic, GPU inference đã pass hay luật/server DRES hiện tại. Cần report dữ liệu/model/integration, nhãn và protocol benchmark, phép đo phần cứng, cùng cấu hình được BTC/giảng viên xác nhận.

Trước demo, chạy các checks trong README và đọc report thật. Chuẩn bị giải thích vì sao core visual vẫn chạy khi thiếu OCR/ASR, vì sao media URL qua ID, vì sao DRES secret ở backend và vì sao phải khóa encoder identity. Phân biệt latency với quality, fixture với dataset thật, và profile 2024 với luật thi hiện tại.

Bạn đã học toàn bộ luồng hiện thực. Bước tiếp theo là gán nhãn query/event trên video thật, phân tích lỗi, chạy ablation trên dev, chốt cấu hình rồi đo test. Chỉ tăng quy mô sau inventory và dự toán disk/RAM; không cần tải model lớn trước khi hiểu dữ liệu và thuật toán hiện có.
