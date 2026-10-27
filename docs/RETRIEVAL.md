# Truy vấn và giải thích điểm xếp hạng

`app/retrieval.py::RetrievalService` nhận request dict đã được `SearchRequest` validate. Backend chạy service trong thread, frontend nhận ID, video timestamp, URL media và evidence. Không trả đường dẫn ổ E/D vào response.

## Visual text, image và example

Luồng visual là `search()` → `_visual()` → `OpenClipEncoder.encode_text()` → `NumpyShardIndex.search()` → resolve metadata → `_result()`. Text/image encoder dùng cùng checkpoint, transform, dimension và L2 normalization. Cosine = inner product vì norm mỗi vector bằng 1. Không dùng softmax top-k làm xác suất đúng.

`NumpyShardIndex.search()` tìm exact theo block, áp dụng filter trước top-k. Query không filter chỉ resolve metadata top candidates từ SQLite, không materialize tất cả keyframe rows. Filter video/time có thể cần giữ tập ID đã lọc trong RAM; đây là giới hạn cần đo khi scale. Tie-break theo ID giúp tái hiện thứ hạng.

`search_image()` giới hạn upload bytes và pixel, decode bằng Pillow rồi gọi cùng image encoder. `search_example()` lấy vector của keyframe đã có trong index, không re-encode bằng model khác. Trong `contest_mode=true` và `task_type=video_kis`, cả upload và example đều bị server chặn theo profile AIC2024, không chỉ ẩn nút website.

CLIP mặc định này chủ yếu phù hợp mô tả tiếng Anh. Query tiếng Việt không được mặc nhiên coi có chất lượng tương đương. Request có `visual_query` riêng để người dùng nhập mô tả tiếng Anh, còn `query` tiếng Việt dành OCR/ASR. Không có translator tự động hoặc API trả phí được gọi ngầm.

## Boolean grammar và Unicode

`app/text_search.py::BooleanParser` dùng recursive descent, không `eval`, không ghép SQL từ raw query. Grammar:

```text
expr  = and_expr (OR and_expr)*
and_expr = unary ((AND)? unary)*
unary = NOT unary | '(' expr ')' | term | '"phrase"'
```

Operators phải viết hoa `AND/OR/NOT`. `NOT` có precedence cao nhất, sau đó `AND`, sau đó `OR`. Các term liền nhau ngầm AND. Ví dụ `"xe đỏ" AND NOT dừng`, `đỏ OR (xanh AND xe)`. Phrase yêu cầu tokens theo thứ tự liền nhau. Query malformed/ngoặc chưa đóng trả lỗi, không im lặng đoán ý định.

Tokenization NFC + casefold dùng Unicode letters/digits, giữ dấu tiếng Việt, chưa stemming hoặc word segmentation tiếng Việt. `do` khác `đỏ`; từ ghép `xe máy` gồm hai token. Dữ liệu giữ text gốc để hiển thị. `TextIndex` là baseline nhỏ với posting dict và kiểm tra phrase bằng vị trí tokens. Production `search_database()` biên dịch AST thành predicates với parameters và tìm qua SQLite FTS5 `unicode61 remove_diacritics 0`.

## BM25 và VSM

TextIndex BM25 dùng `k1=1.2`, `b=0.75`:

```text
idf(t) = log(1 + (N - df(t) + 0.5)/(df(t) + 0.5))
score(d,q) = Σ qtf(t) * idf(t) * tf(t,d)*(k1+1)
                         / (tf(t,d) + k1*(1-b+b*len(d)/avglen))
```

Production dùng FTS5 BM25: SQLite trả giá trị âm cho match tốt; adapter đổi dấu để score lớn hơn xếp trước. Hằng số và handling IDF của FTS5 khác công thức lab, nên không tuyên bố raw scores hai engine giống nhau. Boolean AST quyết định candidate set trước ranking. Query chỉ `NOT` không có positive term, score 0 với tie-break ID.

Lab `TextIndex.search(..., method='tfidf')` dùng `tf=1+log(count)`, `idf=log((N+1)/(df+1))+1`, cosine VSM. TF-IDF hữu ích để hiểu weighting nhưng khác BM25 production. `python -m app.cli lab` chạy ví dụ được ghi nhãn fixture; không coi ví dụ đó là chất lượng retrieval của video thật.

## Text segment → keyframe

`_text()` lấy top segment rồi dùng index SQLite `(video_uid,timestamp_ms)` tìm frame cùng video nằm trong `[start_ms,end_ms]`. Nếu interval không chứa frame, chỉ chọn frame gần biên nhất khi cách biên không quá 1000 ms. Time filter vẫn áp dụng cho anchor. Khoảng 1 giây là quy tắc công khai hiện tại, có thể bỏ match khi sampling thưa hơn; không tự gán mọi câu ASR cho mọi frame của video.

Evidence gồm source, segment ID, khoảng thời gian, BM25 và text gốc. Khi nhiều segment map cùng frame trong cùng channel, giữ score tốt nhất. Khoảng ASR dài có thể map nhiều frame nằm bên trong interval, OCR point chỉ map frame tại điểm/gần biên. Khi thiếu keyframes, text có thể tồn tại nhưng không có result anchor để website seek; cần chạy extraction trước.

## Hybrid bằng weighted RRF

`weighted_rrf()` hợp nhất trên keyframe ID:

```text
RRF(frame) = Σ channel_weight / (60 + rank_in_channel)
```

Cosine, BM25 khác thang nên không cộng raw scores. Contribution mỗi channel ghi rank, raw score và RRF contribution. Mỗi ID nhận tối đa một contribution/channel; weight 0 vô hiệu channel. Ví dụ frame đứng thứ 2 visual và thứ 1 OCR, weights 1 và 2 có score `1/62 + 2/61`. Đây là điểm xếp hạng, không confidence.

Kênh chưa có dữ liệu được capabilities giải thích. Hybrid vẫn dùng các kênh hiện có; lỗi weights/model tạo warning hoặc 503 khi không còn kênh khả dụng. Không giả rằng OCR/ASR đã extract chỉ vì adapter tồn tại.

## Temporal A rồi B

`search(mode='temporal')` tìm A/B độc lập, fusion từng event rồi gọi `temporal_pairs()`. Cặp chỉ hợp lệ khi cùng video và `max(1,min_gap_ms) <= B_ms - A_ms <= max_gap_ms`. B luôn phải sau A; `min_gap_ms=0` vẫn không chấp nhận gap 0.

Candidate B được group theo video, sort timestamp và tìm biên bằng binary search. Upstream giới hạn candidate tối đa 2000/channel; không tạo ma trận NxN toàn kho. Những cặp top-k giữ score trung bình của RRF A/B và evidence riêng. Pair trả ID/timestamp B và `gap_ms`; URL video vẫn video chung. Điều này là bounded candidate retrieval, có thể bỏ cặp tốt nằm ngoài candidate depth; cần đánh giá khi có nhãn thật.

Ví dụ A ở 12000, min gap 1000, max gap 3000: B tại 13000 và 15000 hợp lệ; B tại 15001, 12000 hoặc video khác bị loại. Tests bao gồm đúng các biên milliseconds này.

## Feedback, expansion và diversity

Feedback lưu theo session trong SQLite. Khi `use_feedback=true`, visual query dùng Rocchio:

```text
q' = normalize(q + 0.75 * mean(relevant_vectors)
                 - 0.25 * mean(irrelevant_vectors))
```

Vector feedback lấy từ cùng phiên bản index; ID không còn trong index bị bỏ qua. `index.vector()` trả bản sao nên feedback không sửa mmap hoặc embedding space. Đây là relevance feedback, không fine-tuning. Phiên bản hiện tại không cache query embeddings/kết quả; vì vậy không có stale query cache sau reset/session/index update.

`expansion` là list người dùng nhập và nhìn thấy. Text search thêm OR phrase; visual append terms. Không dùng LLM để tự suy expansion và không dịch giả. So sánh baseline với expansion phải trên nhãn dev/test được tách đúng, không tune bằng test labels.

`group_by_video=true` giữ result tốt nhất mỗi video để xem đa dạng hơn. Khi tắt, trả nguyên rank; benchmark cần ghi rõ option này, không âm thầm deduplicate event. Dedupe frame diễn ra trong RRF theo cùng keyframe ID, không tự coi nhiều frame gần nhau là nhiều relevant event.

## Khả dụng và kiểm tra

`capabilities()` không tải model hoặc network. Nó kiểm tra CURRENT, manifest/shards và local checkpoint cache, số OCR/ASR rows. Mọi API visual vẫn kiểm tra encoder ID thực sau khi nạp model; cached weight khác checksum/preprocessing bị từ chối. Index bị checksum/mapping lỗi khiến visual unavailable, trong khi OCR/ASR còn có thể hoạt động.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_retrieval.py -q
.venv\Scripts\python.exe -m app.cli evaluate '.\labels_reviewed.json' --top-k 10 --output '.\data\evaluation\report.json'
```

Tests là contract/thuật toán với vector và text kiểm chứng được: filter trước top-k, L2, same-D khác encoder, corrupt shard/map, temporal cùng video/thứ tự, RRF, phrase/NOT và feedback không sửa index. Semantic quality của OpenCLIP trên HCMAI24 cần query/ground truth thật; không suy Recall/MRR từ fixture.

Bài tự kiểm tra: tại sao OCR BM25 1,000,000 không được cộng vào cosine 0.9? Đáp án: chúng không có cùng đơn vị/phân phối; weighted RRF dùng rank để hợp nhất và giữ raw scores làm evidence. RRF cũng không là xác suất rằng điểm video đúng.
