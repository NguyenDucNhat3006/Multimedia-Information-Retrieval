# Ánh xạ đề cương CS336 sang hệ thống và bài lab

Nguồn là bản scan `references/de_cuong_CS336.pdf` đã đọc trực tiếp ảnh render: 14 trang PDF, bìa cập nhật 05/2023. **Đề cương học phần không phải rubric đồ án riêng**: bảng này chỉ minh bạch chương nào được áp dụng trong sản phẩm, minh họa bằng lab, hoặc mới giải thích. Không tự coi mọi chương là tính năng bắt buộc/đã hoàn thành toàn bộ.

Số trang dưới đây là trang PDF từ 1 (PDF p3 in số trang 1). Bằng chứng đọc ở `docs/reference_audit/`. Kết quả thực nghiệm và giới hạn model/dataset đọc thêm báo cáo kiểm thử, không suy chất lượng từ một lab đúng.

| Chương theo tài liệu thực | Trang PDF | Trạng thái trong đồ án | Vị trí code và nội dung cần bảo vệ |
|---|---|---|---|
| 1 Giới thiệu | 3,5 | Giải thích + hệ thống ứng dụng | Bài toán tìm sự kiện video, text/ảnh/audio; backend/website/pipeline, kiến trúc các tầng. Giải thích IR khác hệ thống trả lời chatbot; rank score khác xác suất đúng |
| 2 Các mô hình truy vấn căn bản với dữ liệu text | 5–6 | Core Boolean/BM25; lab VSM/TF-IDF | `app/text_search.py`: parser AST AND/OR/NOT, phrase, posting; FTS5 ranking thực tế. `app.labs.run_labs`: cosine TF-IDF trên 3 document. TF-IDF dùng Boolean candidate filter trước ranking, không search mọi document không khớp term |
| 3 Từ khóa (Term) và xử lý từ khóa trong truy vấn | 6 | Core | NFC + casefold, giữ dấu tiếng Việt, Unicode token, phrase với token liền nhau, text gốc hiển thị. Chưa stemming/tách từ ghép tiếng Việt; “thành phố” thành 2 term, cần phrase khi muốn liền nhau |
| 4 Chỉ mục (Index) và các kỹ thuật xây dựng chỉ mục tìm kiếm | 6 | Core index local; lab posting dictionary; BSBI/SPIMI đầy đủ và phân tán: giải thích | SQLite FTS5 + index vector shard/memmap, manifest/checksum/row map, staging/publish/resume. `TextIndex` minh họa tạo postings theo term như bước đầu SPIMI, **không có block spill/merge của SPIMI đầy đủ**. BSBI sắp cặp term/doc rồi merge; MapReduce/distributed index chưa triển khai. Process worker local không được gọi là hệ phân tán |
| 5 Đánh giá các hệ thống truy vấn (Evaluation) | 6–7 | Core tool đánh giá; nhãn/benchmark thực theo trạng thái report | `app/evaluation.py`: schema query/event/interval, binary/graded labels; P@K, event Recall@K, MRR, nDCG@K; AP/mAP khi judgment đủ. Một event chỉ gain một lần dù nhiều frame gần nhau. Nhãn human_reviewed/split rõ. Không có nhãn thật thì chưa có kết luận chất lượng; fixture chỉ test công thức |
| 6 Các phương pháp khai thác phản hồi người dùng (Relevance Feedback) | 8 | Core | `app/retrieval.py`: Rocchio trên vector, relevant/non-relevant theo session, normalization lại; query expansion do người dùng nhập; reset feedback không sửa embedding. Giải thích vai trò alpha/beta/gamma và khác biệt implicit/explicit feedback |
| 7 Truy vấn dữ liệu Web (Web Search) và các kỹ thuật phân tích liên kết (Link Analysis) | 8 | Lab PageRank local; crawling/index Web/HITS: giải thích | `app/labs.py:pagerank` với graph nhỏ và dangling node; không crawler, không thu thập web hay dùng PageRank để tìm frame. Giải thích web graph, hubs/authorities/HITS, damping và dangling mass |
| 8 Phân lớp (Categorization) và Gom cụm (Clustering) | 9 | Lab minh họa | `app/labs.py:kmeans` seed42, Lloyd Euclidean trên 4 vector 2D; `run_labs` gán category bằng cosine với 2 prototype. Đây là prototype classifier minh họa, không model được train/đánh giá trên dataset thật; không đổi index retrieval bởi label lab |
| 9 Truy vấn với dữ liệu thị giác (Visual Information Retrieval) | 9 | Core | `app/encoders.py`, `app/index.py`: image/text cùng OpenCLIP space, L2 norm, cosine/inner product, capability khi thiếu weights. So sánh đặc trưng toàn cục với local feature và giới hạn ngôn ngữ CLIP |
| 10 Truy vấn ảnh | 10 | Core trong nghiên cứu/luyện tập; contest Video KIS chặn backend | Upload ảnh/query-by-example cùng encoder, validate ảnh, top-k thực; frontend và backend kiểm tra contest rule. Không áp dụng input ảnh chụp clip đề thi Video KIS bị cấm trong DOCX 2024 |
| 11 Truy vấn video | 10 | Core | `app/pipeline.py`: keyframe/PTS/timeline; `app/retrieval.py:temporal_pairs`: A rồi B cùng video có min/max gap ms; OCR/ASR segment time mapping, fusion weighted RRF. Đây là retrieval qua frame/segment, chưa video foundation model hiểu cả motion dài |
| Thực hành xây hệ thống text, thị giác và hướng dẫn đồ án | 11 | Core + hướng dẫn | CLI pipeline/doctor/inspect, website seek/neighbor/feedback/candidates, report tái hiện. Người học cần giải thích được luồng input→index→rank→timestamp→DRES, thay đổi tham số và phân tích lỗi |

## Lab chạy được và cách đọc kết quả

```powershell
.venv/Scripts/python.exe -m app.cli lab
```

`provenance="labelled_fixture"` trong output phân biệt với dữ liệu thật. Lệnh đọc 3 câu text và 4 vector synthetic cố định, không tải model/network và không ingest kho video.

Kết quả quan sát ngày 14/10/2026:

- Boolean `xe AND NOT xanh` trả `d1: xe đỏ chạy qua cầu`, score0 vì Boolean không xếp hạng mức độ liên quan.
- VSM `xe đỏ` trên Boolean candidates trả d1 với cosine TF-IDF khoảng `0.6500572791`; đây là similarity của lab, không xác suất đúng.
- K-means labels `[0,0,1,1]`; centroid xấp xỉ `[0.975,0.075]`, `[0.075,0.975]`. Cosine category `[0,0,1,1]` theo hai prototype `[1,0]`,`[0,1]`. Cluster số 0/1 không có ngữ nghĩa tự nhiên nếu không gán nhãn.
- PageRank graph A→B,C; B→C; C→A; D dangling cho A≈0.369324, B≈0.204582, C≈0.378476, D≈0.047619; tổng≈1. Kết quả phản ánh liên kết graph local, không relevance video.

Người học nên đổi một document, query Boolean/phrase, liên kết graph, số cluster hoặc prototype rồi dự đoán trước khi chạy. Lab thể hiện thuật toán nhỏ; chưa là công cụ phân lớp/gom cụm Web ở quy mô lớn.

## Chuẩn đầu ra và môi trường

PDF p4: CLO1 hiểu/trình bày khái niệm và xử lý dữ liệu đa phương tiện; CLO2 phân tích/đánh giá giải pháp; CLO3 xây giải pháp; CLO4 thuật ngữ tiếng Anh; CLO5 làm việc nhóm/thuyết trình. Bảng ánh xạ, glossary, test/report và phần phân tích lỗi hỗ trợ các chuẩn này; không tự chấm mức hoàn thành học phần của người học.

PDF p13 yêu cầu Python và Linux trên máy cá nhân/máy ảo. Dự án có Windows native/PowerShell để dùng dữ liệu/GPU hiện có, đồng thời có hướng dẫn Linux tương đương. Việc chạy Windows không được ghi là đã thực hành Linux; không cần máy ảo chỉ để chạy smoke test local.
