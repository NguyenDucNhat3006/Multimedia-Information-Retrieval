# Đọc tài liệu gốc

Ngày đọc: 14/10/2026. Tài liệu gốc được giữ nguyên byte.

| Nguồn | SHA256 | Cách đọc thực tế |
|---|---|---|
| `references/de_cuong_CS336.pdf` | `f4d5d47c6ffb4dc047adb8cb9cf3134052d5edfeae458d4d97814565dcc66ff0` | pypdf xác nhận 14 trang và 0 ký tự text tất cả trang; Poppler render rồi nhìn ảnh bìa, PDF trang 3–11,13 |
| `references/THONG TIN HE THONG THI VONG CHUNG KET AIC2024.docx` | `07fb1b59a185d75bfbde838a9a28cdea6c94fdea88be5bce76d0fb8846466948` | OOXML đọc paragraph/table; trích ảnh công thức và nhìn trực tiếp; whole-document renderer không chạy được vì thiếu LibreOffice |

Ảnh `course-XX.png` dùng số trang **PDF 1-based**, khác số in dưới trang (PDF p3 in số 1). Bìa ghi cập nhật 05/2023, PDF p13 ký ngày 22/05/2023. Bản scan là đề cương học phần, không một rubric riêng của đồ án.

## Nội dung xác nhận từ ảnh

| Chương/khối | Vị trí PDF | Nội dung chính |
|---|---|---|
| Giới thiệu | 3,5 | Dữ liệu text/ảnh/video, ứng dụng, thách thức |
| 2 Các mô hình truy vấn căn bản với dữ liệu text | 5–6 | Boolean Retrieval Model, Vector Space Model, ưu/nhược |
| 3 Từ khóa (Term) và xử lý từ khóa trong truy vấn | 6 | Term và xử lý văn bản |
| 4 Chỉ mục (Index) và các kỹ thuật xây dựng chỉ mục tìm kiếm | 6 | BSBI, SPIMI, Distributed Computing, MapReduce |
| 5 Đánh giá các hệ thống truy vấn (Evaluation) | 6–7 | Xây dựng dữ liệu đánh giá, relevance nhị phân/nhiều cấp độ |
| 6 Các phương pháp khai thác phản hồi người dùng | 8 | Relevance Feedback, Reweighting, Query Expansion |
| 7 Truy vấn dữ liệu Web và các kỹ thuật phân tích liên kết | 8 | Crawling, Web Indexes, Graph, Hubs/Authorities, PageRank |
| 8 Phân lớp (Categorization) và Gom cụm (Clustering) | 9 | Khái niệm, phương pháp, ứng dụng trong IR |
| 9 Truy vấn với dữ liệu thị giác | 9 | Visual Information Retrieval, ảnh/video, mô hình tổng quát |
| 10 Truy vấn ảnh | 10 | Đặc trưng cục bộ/toàn cục/kết hợp, so sánh, image understanding |
| 11 Truy vấn video | 10 | Trích đặc trưng, so sánh, video understanding |
| Thực hành | 11 | Xây hệ thống text/thị giác; hướng dẫn quá trình đồ án |
| Môi trường | 13 | Python, Linux trên máy cá nhân/máy ảo |

PDF p4 nêu CLO1 trình bày khái niệm/xử lý; CLO2 phân tích/đánh giá; CLO3 xây giải pháp; CLO4 hiểu thuật ngữ tiếng Anh; CLO5 làm việc nhóm/thuyết trình. Tài liệu dạy học dự án cần liên hệ đầy đủ và phân biệt tính năng chạy thật, lab minh họa và nội dung chỉ giải thích. Windows native là lựa chọn của dự án, khác môi trường Linux ghi trong đề cương.

DOCX xác nhận Video KIS cấm chụp/ghi điện tử clip đề thi để đưa vào công cụ; clip không quá 20 giây; QA answer chỉ ký tự 0–9. Hạn Video KIS 4 phút, Textual KIS/QA 5 phút. QA format `<ANSWER>-<VIDEO_ID>-<TIME(ms)>`; tên video bỏ extension; không nộp trùng cùng query. Địa chỉ/thời gian server thi thử trong tài liệu là lịch sử 15–20/10/2024, không kiểm chứng hoạt động hiện nay.

`image2-white.png` chỉ đặt ảnh equation gốc lên nền trắng để đọc transparency, không đổi biểu thức. Ảnh gốc `image2.png` bảo toàn byte trích từ DOCX. Công thức `max(0,50+50·fTs(t)−10·ws)`, văn bản giải thích phần thời gian giảm tuyến tính 50 về 0 trong `[0,tL]`, cho `fTs(t)=1−t/tL`.

Các PNG ở đây là bằng chứng đọc tham khảo local, không frontend assets và không ground truth video retrieval.
