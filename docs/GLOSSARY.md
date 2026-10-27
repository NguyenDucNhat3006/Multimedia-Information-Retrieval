# Thuật ngữ CS336 dùng trong dự án

Các thuật ngữ gắn với source thực và chương 1–11 trong đề cương, phục vụ CLO4 đọc/trình bày tiếng Anh. Các ví dụ thời gian dùng integer milliseconds; score xếp hạng không là xác suất đúng.

| Thuật ngữ tiếng Anh | Nghĩa và ví dụ trong hệ thống |
|---|---|
| Information Retrieval (IR) | Truy vấn thông tin: xếp hạng đối tượng có khả năng liên quan để người dùng kiểm chứng; tìm frame video, không tự suy kết quả đúng chỉ từ similarity |
| Multimedia Information Retrieval | IR trên nhiều loại dữ liệu: text, ảnh, audio, video; mỗi loại có extractor/representation/ranker riêng |
| Query | Yêu cầu truy vấn; câu tiếng Việt giữ cho OCR/ASR và có thể bổ sung `visual_query` tiếng Anh cho OpenCLIP, không dịch giả |
| Document / Retrieval unit | Đơn vị tìm kiếm: text segment ở text index, keyframe ở vector index; event là đơn vị ground truth. Cần nêu đơn vị khi tính metrics |
| Term / Tokenization | Term là đơn vị chỉ mục; tokenizer NFC+casefold và giữ dấu, “thành phố” thành 2 term. Tokenizer không phải bộ hiểu ngôn ngữ |
| Unicode normalization (NFC) | Ghép tổ hợp ký tự về một dạng nhất quán để query/ingest trùng nhau; không tự bỏ dấu tiếng Việt |
| Boolean Retrieval Model (BRM) | AND giao tập, OR hợp tập, NOT phần bù. `xe AND NOT xanh` lọc các document chứa xe mà không chứa xanh |
| Phrase query | Query chuỗi term liền nhau: `"cầu vượt"` khác `cầu AND vượt`; parser không dùng Python eval |
| Inverted index / Posting list | Chỉ mục đảo term→doc IDs; giúp tìm từ khóa không quét toàn văn bản. SQLite FTS5 là index thực tế |
| Vector Space Model (VSM) | Biểu diễn document/query thành vector term rồi so độ tương đồng; lab dùng cosine TF-IDF sau Boolean filter |
| TF-IDF | Term Frequency × Inverse Document Frequency: term thường trong một document và hiếm trong tập có trọng số lớn. Công thức TF/IDF cụ thể phải đọc code, không chỉ tên thuật toán |
| BM25 | Ranking lexical có saturation TF và chuẩn hóa độ dài. Production FTS5 có BM25; không cộng trực tiếp điểm này với cosine vì khác thang |
| BSBI (Blocked Sort-Based Indexing) | Chia khối, sắp cặp term/document, ghi block rồi merge; chỉ giải thích trong dự án, chưa triển khai external-memory BSBI |
| SPIMI (Single-Pass In-Memory Indexing) | Tạo dictionary/postings trong memory rồi spill/merge block khi đầy. `TextIndex` minh họa postings, chưa toàn bộ SPIMI spill/merge |
| Distributed Computing / MapReduce | Chia tính toán trên nhiều máy, map dữ liệu rồi reduce nhóm. Worker process trên cùng máy không tự là hệ phân tán |
| Feature extraction | Rút trích đặc trưng, ví dụ encoder chuyển ảnh/text thành vector; cần biết encoder/checkpoint/preprocessing để vector có nghĩa |
| Embedding / Encoder space | Vector đặc trưng. Image/text OpenCLIP phải cùng encoder space; hai vector cùng dimension chưa đủ để ghép index |
| L2 normalization | Chia vector cho norm để độ dài bằng1; vector norm0 phải bị xử lý. Sau normalization, inner product bằng cosine |
| Cosine similarity / Inner product | Cosine đo góc; inner product là tích vô hướng. Dùng với vector đã L2-normalize cho cosine search; score0.8 không là “80% đúng” |
| Exact / Approximate Nearest Neighbor (ANN) | Exact so đầy đủ vector hợp lệ; ANN giảm chi phí qua index với tradeoff recall. NumPy block search exact; FAISS/Milvus tùy adapter |
| Manifest / Provenance | Metadata phiên bản encoder, dimension, normalization, mapping/checksum và nguồn dữ liệu; provenance giúp phân biệt fixture, dữ liệu thật, ground truth |
| Staging / Atomic publish | Xây index ở vùng tạm, validate rồi đổi version bằng một thao tác; website không thấy nửa index cũ/nửa mới |
| Checkpoint / Resume | Mốc chứng minh bước dữ liệu đã commit để tiếp tục sau lỗi; số file đã đi qua vòng lặp chưa là checkpoint ghi index thành công |
| Keyframe / Original frame index | Keyframe là ảnh đại diện; ordinal ảnh thứ12 không nhất thiết frame gốc12. Frame index gốc bắt đầu từ0 khi decoder xác định được |
| PTS / Time base | Presentation Timestamp và đơn vị tick của stream dùng tính mốc hiển thị frame; quy về timeline bắt đầu0, chuyển thành ms đúng nguồn |
| CFR / VFR / FPS | Constant/Variable Frame Rate và frames per second. VFR không dùng frame_index/average_FPS để đo timestamp. Không fallback25FPS khi nộp |
| Video UID / Media item name | UID là ID nội bộ phân biệt batch; DRES media name là tên file bỏ extension do BTC dùng. Tên trùng chặn submit, không tự thêm batch vào payload |
| OCR / ASR | Optical Character Recognition đọc chữ trên hình; Automatic Speech Recognition nhận lời nói. Kênh chỉ khả dụng khi có import/extraction thật, không sinh dữ liệu giả |
| Segment / Temporal alignment | Đoạn OCR/ASR có start/end ms; map vào frame đúng video/time, không gán một câu ASR cho tất cả frame video |
| Rank fusion / Weighted RRF | Kết hợp thứ hạng từ nhiều kênh; weighted Reciprocal Rank Fusion cộng `weight/(constant+rank)`, không cộng raw cosine/BM25 |
| Temporal retrieval | Tìm A trước B trong cùng video với min/max gap; trả timestamp và chứng cứ cả hai sự kiện, không chỉ boost A khi không có B |
| Relevance feedback / Rocchio | User đánh liên quan/không liên quan; Rocchio dịch vector query về centroid dương và xa centroid âm, normalization lại. Feedback theo session và reset được |
| Reweighting / Query expansion | Chỉnh trọng số hoặc thêm term/query diễn đạt; expansion user nhập minh bạch, không mặc định gọi LLM/API trả phí |
| Web crawling / Web index | Thu thập và xây index web; chỉ giải thích trong đồ án này, không chạy crawler |
| Link analysis / Hubs and authorities | Xếp hạng dựa đồ thị liên kết; hub trỏ tới nguồn tốt, authority nhận liên kết tốt. HITS chỉ giải thích |
| PageRank / Dangling node | Xác suất random walk với damping; node không outlink phân phối mass đều. Lab graph local, không dùng làm score semantic frame |
| Categorization / Clustering | Phân lớp gán nhóm đã biết; gom cụm tự tìm nhóm trong vector. Lab prototype cosine khác k-means và chưa model được train trên dataset video |
| K-means / Centroid | Lloyd iteration gán point về tâm gần rồi cập nhật trung bình; lab Euclidean seed cố định, giữ tâm cũ nếu cluster rỗng |
| Ground truth / Relevance judgment | Nhãn do người kiểm duyệt: video/event interval/grade. Retrieval top-1 hoặc score cao không tự là ground truth |
| Binary / Graded relevance | Liên quan0/1 hoặc nhiều mức; nDCG dùng grade, metric nhị phân dùng grade>0. Nhãn cần schema rõ |
| Precision@K / Recall@K | P@K số slot hit sự kiện relevant/K; event Recall@K số relevant event đã hit/tổng relevant event. Frame thứ hai cùng event không thêm gain |
| MRR / AP / mAP | Mean Reciprocal Rank theo hit đầu; Average Precision tổng precision ở hit phù hợp; mAP trung bình AP query. AP/mAP chỉ công bố khi judgments đầy đủ theo tool |
| nDCG@K | Normalized Discounted Cumulative Gain: gain nhiều mức giảm theo vị trí, chia ideal DCG; duplicate event không tăng gain |
| Train / Dev / Test split | Tập học/tune/đánh giá cuối; không dùng nhãn test để chọn trọng số fusion rồi báo là đánh giá độc lập |
| Ablation | Bỏ/thêm từng thành phần (visual/OCR/ASR/hybrid/temporal/feedback) để xem đóng góp; kênh thiếu dữ liệu ghi N/A |
| Latency p50 / p95 | Trung vị và phân vị95 thời gian; nêu sample count, cold/warm, phần cứng/model/network; không suy từ một request |
| Known-Item Search (KIS) | Tìm một đối tượng/sự kiện đã mô tả. Textual KIS bằng mô tả; Video KIS bằng clip đề thi, luật2024 cấm chụp/ghi clip để đưa công cụ |
| DRES / Evaluation / Task | Distributed Retrieval Evaluation Server; evaluation là cuộc/phiên, task là từng query/round. Task key riêng cần cho chống trùng |
| Dry run / Mock / Live | Dry run chỉ chuẩn bị/lưu không network; mock chấm nhãn local+clock; live gọi server backend cấu hình. Điểm mock không verdict chính thức |
| Submission ledger / Reservation | Nhật ký SQLite bền vững; unique reservation trước POST ngăn double-click/đa tab/restart nộp cùng đáp án. Timeout giữ unknown không auto retry |
| Accepted pending / Verdict | Accepted chưa có kết luận khác correct/incorrect. HTTP200/202 và status=true chưa chứng minh đáp án đúng; parse field submission enum khóa |
| Fixture | Dữ liệu kiểm thử có nguồn/nhãn khai báo, kiểm tra thuật toán/contract; không benchmark đại diện kho116GB |

Đọc `docs/COURSE_MAPPING.md` để biết thuật ngữ nào có core code, lab hoặc chỉ giải thích; `docs/DRES_INTEGRATION.md` mô tả protocol và giới hạn lịch sử AIC2024.
